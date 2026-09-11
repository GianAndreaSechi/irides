import boto3
from botocore.exceptions import BotoCoreError, ClientError
from typing import List, Dict, Any, Optional
from core.db_connector.interface import BaseConnector
from core.db_connector.models import Instance, Schema, Table, Column, TableDescription
from core.db_connector.models.table_details import Partition
from core.db_connector.sql_utils import validate_limit_offset
from loguru import logger
from ..cache_manager import CacheManager


class AthenaConnector(BaseConnector):
    """
    A database connector for Amazon Athena backed by the AWS Glue Data Catalog.

    Connection params:
        - catalog (str): Glue catalog name. Default: "AwsDataCatalog".
        - region (str): AWS region (required).
        - s3_output_location (str): S3 URI for Athena query results (required for
          query execution, not used for metadata operations).
        - aws_access_key_id (str): Optional. Falls back to environment / IAM role.
        - aws_secret_access_key (str): Optional.
        - aws_session_token (str): Optional.

    Metadata is fetched via the Glue API (faster than running Athena queries).
    Foreign keys and primary keys are not enforced by Athena and are therefore
    always returned as empty / None.
    """

    @staticmethod
    def get_type() -> str:
        return "athena"

    def __init__(self, connection_params: Dict[str, Any], cache_manager: CacheManager):
        super().__init__(connection_params, cache_manager)

        self.catalog = connection_params.get("catalog", "AwsDataCatalog")
        self.region = connection_params.get("region")
        if not self.region:
            raise ValueError("Athena connector requires 'region' in connection_params.")

        boto_kwargs: Dict[str, Any] = {"region_name": self.region}
        if connection_params.get("aws_access_key_id"):
            boto_kwargs["aws_access_key_id"] = connection_params["aws_access_key_id"]
        if connection_params.get("aws_secret_access_key"):
            boto_kwargs["aws_secret_access_key"] = connection_params["aws_secret_access_key"]
        if connection_params.get("aws_session_token"):
            boto_kwargs["aws_session_token"] = connection_params["aws_session_token"]

        try:
            self._athena = boto3.client("athena", **boto_kwargs)
            self._glue = boto3.client("glue", **boto_kwargs)
            # Lightweight connectivity check
            self._athena.list_data_catalogs()
            logger.info(f"Successfully connected to Athena (region={self.region}, catalog={self.catalog})")
        except (BotoCoreError, ClientError) as e:
            logger.exception("Failed to connect to Athena.")
            raise ConnectionError(f"Failed to connect to Athena: {e}")

    # ------------------------------------------------------------------
    # list_instances  →  Athena data catalogs
    # ------------------------------------------------------------------

    def list_instances(self, no_cache: bool = False) -> List[Instance]:
        cache_key = f"athena_instances:{self.region}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Instance(**d) for d in cached_data]

        try:
            paginator = self._athena.get_paginator("list_data_catalogs")
            instances: List[Instance] = []
            for page in paginator.paginate():
                for catalog in page.get("DataCatalogsSummary", []):
                    instances.append(Instance(name=catalog["CatalogName"], version=None))
        except (BotoCoreError, ClientError) as e:
            logger.exception("Failed to list Athena data catalogs.")
            raise RuntimeError(f"Failed to list Athena data catalogs: {e}")

        self.cache_manager.set_cached_data(cache_key, [i.model_dump() for i in instances])
        return instances

    # ------------------------------------------------------------------
    # list_schemas  →  Glue databases within a catalog
    # ------------------------------------------------------------------

    def list_schemas(self, instance_name: str, no_cache: bool = False) -> List[Schema]:
        cache_key = f"athena_schemas:{self.region}:{instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Schema(**d) for d in cached_data]

        try:
            paginator = self._athena.get_paginator("list_databases")
            schemas: List[Schema] = []
            for page in paginator.paginate(CatalogName=instance_name):
                for db in page.get("DatabaseList", []):
                    schemas.append(Schema(name=db["Name"]))
        except (BotoCoreError, ClientError) as e:
            logger.exception(f"Failed to list databases for catalog '{instance_name}'.")
            raise RuntimeError(f"Failed to list databases for catalog '{instance_name}': {e}")

        self.cache_manager.set_cached_data(cache_key, [s.model_dump() for s in schemas])
        return schemas

    # ------------------------------------------------------------------
    # list_tables  →  Glue tables within a database
    # ------------------------------------------------------------------

    def list_tables(
        self,
        instance_name: str,
        schema_name: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        no_cache: bool = False,
    ) -> List[Table]:
        limit, offset = validate_limit_offset(limit, offset)
        cache_key = f"athena_tables:{self.region}:{instance_name}:{schema_name}:{limit}:{offset}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Table(**d) for d in cached_data]

        try:
            paginator = self._athena.get_paginator("list_table_metadata")
            all_tables: List[Table] = []
            for page in paginator.paginate(CatalogName=instance_name, DatabaseName=schema_name):
                for tbl in page.get("TableMetadataList", []):
                    all_tables.append(Table(name=tbl["Name"], schema_name=schema_name))
        except (BotoCoreError, ClientError) as e:
            logger.exception(f"Failed to list tables for '{instance_name}.{schema_name}'.")
            raise RuntimeError(f"Failed to list tables for '{instance_name}.{schema_name}': {e}")

        # Apply offset/limit in-memory (Athena pagination token doesn't support arbitrary offsets)
        start = offset or 0
        end = (start + limit) if limit is not None else None
        tables = all_tables[start:end]

        self.cache_manager.set_cached_data(cache_key, [t.model_dump() for t in tables])
        return tables

    # ------------------------------------------------------------------
    # describe_table  →  columns + partition keys via Glue GetTable
    # ------------------------------------------------------------------

    def describe_table(
        self,
        instance_name: str,
        schema_name: str,
        table_name: str,
        no_cache: bool = False,
    ) -> TableDescription:
        cache_key = f"athena_describe_table:{self.region}:{instance_name}:{schema_name}:{table_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return TableDescription(**cached_data)

        try:
            response = self._glue.get_table(
                DatabaseName=schema_name,
                Name=table_name,
            )
        except (BotoCoreError, ClientError) as e:
            logger.exception(f"Failed to describe table '{instance_name}.{schema_name}.{table_name}'.")
            raise RuntimeError(
                f"Failed to describe table '{instance_name}.{schema_name}.{table_name}': {e}"
            )

        glue_table = response["Table"]
        storage_cols = glue_table.get("StorageDescriptor", {}).get("Columns", [])
        partition_keys = glue_table.get("PartitionKeys", [])

        columns = [
            Column(
                name=col["Name"],
                data_type=col["Type"],
                is_nullable=True,  # Athena / Glue does not enforce NOT NULL
                default_value=None,
                comment=col.get("Comment") or None,
            )
            for col in storage_cols
        ]

        partitions = [
            Partition(
                column_name=pk["Name"],
                data_type=pk["Type"],
                comment=pk.get("Comment") or None,
            )
            for pk in partition_keys
        ]

        table_description = TableDescription(
            instance_name=instance_name,
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            primary_key=None,    # not enforced in Athena
            foreign_keys=[],     # not supported in Athena
            indexes=[],          # Athena has no traditional indexes
            partitions=partitions,
        )
        self.cache_manager.set_cached_data(cache_key, table_description.model_dump())
        return table_description

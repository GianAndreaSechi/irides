try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - optional extra 'aws'
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = ClientError = Exception  # type: ignore[misc,assignment]

from typing import List, Dict, Any, Optional
from core.db_connector.interface import BaseConnector
from core.db_connector.models import Instance, Schema, Table, Column, TableDescription
from core.db_connector.models.table_details import PrimaryKey, Partition, Index
from core.db_connector.sql_utils import validate_limit_offset
from loguru import logger
from ..cache_manager import CacheManager, hash_auth_context

# DynamoDB scalar type codes → human-readable names
_DYNAMO_TYPES: Dict[str, str] = {
    "S": "String",
    "N": "Number",
    "B": "Binary",
}


class DynamoDBConnector(BaseConnector):
    """
    A database connector for Amazon DynamoDB.

    DynamoDB has no schema/namespace concept, so the hierarchy is flattened:
        instance  = AWS region
        schema    = "default"  (fixed — DynamoDB has no schema layer)
        table     = DynamoDB table

    describe_table() returns:
        - columns       : key attributes only (partition key + sort key + GSI/LSI key attrs).
                          Non-key attributes are schemaless and cannot be enumerated
                          without a full table scan.
        - primary_key   : the partition key (HASH attribute).
        - sort_key      : the sort/range key attribute name, if present.
        - partitions    : the partition key as a Partition object (type + name).
        - indexes       : GSIs and LSIs with their own key schemas.
        - foreign_keys  : always empty (not supported by DynamoDB).

    Connection params:
        - region (str): AWS region (required).
        - aws_access_key_id (str): optional.
        - aws_secret_access_key (str): optional.
        - aws_session_token (str): optional.
        - endpoint_url (str): optional, for local DynamoDB (e.g. "http://localhost:8000").
    """

    _FIXED_SCHEMA = "default"

    @staticmethod
    def get_type() -> str:
        return "dynamodb"

    def __init__(self, connection_params: Dict[str, Any], cache_manager: CacheManager):
        super().__init__(connection_params, cache_manager)

        self.region = connection_params.get("region")
        if not self.region:
            raise ValueError("DynamoDB connector requires 'region' in connection_params.")
        if boto3 is None:
            raise ImportError("Missing optional dependency 'boto3'. Install with: pip install 'irides-core[aws]'")

        self.endpoint_url = connection_params.get("endpoint_url")
        self._auth_fingerprint = hash_auth_context(
            connection_params.get("aws_access_key_id"),
            self.endpoint_url,
        )

        boto_kwargs: Dict[str, Any] = {"region_name": self.region}
        for key in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token", "endpoint_url"):
            if connection_params.get(key):
                boto_kwargs[key] = connection_params[key]

        try:
            self._client = boto3.client("dynamodb", **boto_kwargs)
            self._client.list_tables(Limit=1)
            logger.info(f"Successfully connected to DynamoDB (region={self.region})")
        except (BotoCoreError, ClientError) as e:
            logger.exception("Failed to connect to DynamoDB.")
            raise ConnectionError(f"Failed to connect to DynamoDB: {e}")

    def _cache_scope(self) -> str:
        auth = getattr(self, "_auth_fingerprint", "")
        return f"{self.region}:{auth}" if auth else f"{self.region}"

    # ------------------------------------------------------------------
    # list_instances  →  the AWS region as a single instance
    # ------------------------------------------------------------------

    def list_instances(self, no_cache: bool = False) -> List[Instance]:
        cache_key = f"dynamodb_instances:{self._cache_scope()}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Instance(**d) for d in cached_data]

        instances = [Instance(name=self.region, version=None)]
        self.cache_manager.set_cached_data(cache_key, [i.model_dump() for i in instances])
        return instances

    # ------------------------------------------------------------------
    # list_schemas  →  fixed single schema "default"
    # ------------------------------------------------------------------

    def list_schemas(self, instance_name: str, no_cache: bool = False) -> List[Schema]:
        cache_key = f"dynamodb_schemas:{self._cache_scope()}:{instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Schema(**d) for d in cached_data]

        if instance_name != self.region:
            raise ValueError(f"Instance name '{instance_name}' does not match configured region '{self.region}'")

        schemas = [Schema(name=self._FIXED_SCHEMA)]
        self.cache_manager.set_cached_data(cache_key, [s.model_dump() for s in schemas])
        return schemas

    # ------------------------------------------------------------------
    # list_tables
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
        cache_key = f"dynamodb_tables:{self._cache_scope()}:{instance_name}:{schema_name}:{limit}:{offset}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Table(**d) for d in cached_data]

        if instance_name != self.region:
            raise ValueError(f"Instance name '{instance_name}' does not match configured region '{self.region}'")
        if schema_name != self._FIXED_SCHEMA:
            raise ValueError(f"DynamoDB has no schema '{schema_name}'. Use '{self._FIXED_SCHEMA}'.")

        try:
            all_names: List[str] = []
            paginator = self._client.get_paginator("list_tables")
            for page in paginator.paginate():
                all_names.extend(page.get("TableNames", []))
        except (BotoCoreError, ClientError) as e:
            logger.exception("Failed to list DynamoDB tables.")
            raise RuntimeError(f"Failed to list DynamoDB tables: {e}")

        start = offset or 0
        end = (start + limit) if limit is not None else None
        tables = [Table(name=n, schema_name=schema_name) for n in all_names[start:end]]

        self.cache_manager.set_cached_data(cache_key, [t.model_dump() for t in tables])
        return tables

    # ------------------------------------------------------------------
    # describe_table
    # ------------------------------------------------------------------

    def describe_table(
        self,
        instance_name: str,
        schema_name: str,
        table_name: str,
        no_cache: bool = False,
    ) -> TableDescription:
        cache_key = f"dynamodb_describe_table:{self._cache_scope()}:{instance_name}:{schema_name}:{table_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return TableDescription(**cached_data)

        try:
            response = self._client.describe_table(TableName=table_name)
        except (BotoCoreError, ClientError) as e:
            logger.exception(f"Failed to describe DynamoDB table '{table_name}'.")
            raise RuntimeError(f"Failed to describe DynamoDB table '{table_name}': {e}")

        raw = response["Table"]
        attr_types: Dict[str, str] = {
            a["AttributeName"]: _DYNAMO_TYPES.get(a["AttributeType"], a["AttributeType"])
            for a in raw.get("AttributeDefinitions", [])
        }

        # Partition key (HASH) and sort key (RANGE)
        hash_key: Optional[str] = None
        range_key: Optional[str] = None
        for ks in raw.get("KeySchema", []):
            if ks["KeyType"] == "HASH":
                hash_key = ks["AttributeName"]
            elif ks["KeyType"] == "RANGE":
                range_key = ks["AttributeName"]

        # Columns: only key attributes are schema-defined in DynamoDB.
        # Primary key attributes (HASH/RANGE) are required; secondary index attributes are nullable.
        primary_key_attrs = {k for k in (hash_key, range_key) if k is not None}
        key_attr_names: List[str] = [k for k in attr_types]
        columns = [
            Column(
                name=name,
                data_type=attr_types[name],
                is_nullable=(name not in primary_key_attrs),
                default_value=None,
                comment=None,
            )
            for name in key_attr_names
        ]

        primary_key = PrimaryKey(column_names=[hash_key]) if hash_key else None

        partitions = (
            [Partition(column_name=hash_key, data_type=attr_types.get(hash_key, "Unknown"))]
            if hash_key else []
        )

        # GSIs and LSIs → Index objects
        indexes: List[Index] = []
        for gsi in raw.get("GlobalSecondaryIndexes", []):
            indexes.append(self._index_from_key_schema(gsi, "GSI"))
        for lsi in raw.get("LocalSecondaryIndexes", []):
            indexes.append(self._index_from_key_schema(lsi, "LSI"))

        table_description = TableDescription(
            instance_name=instance_name,
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            primary_key=primary_key,
            sort_key=range_key,
            foreign_keys=[],
            indexes=indexes,
            partitions=partitions,
        )
        self.cache_manager.set_cached_data(cache_key, table_description.model_dump())
        return table_description

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _index_from_key_schema(raw_index: Dict[str, Any], index_type: str) -> Index:
        col_names = [ks["AttributeName"] for ks in raw_index.get("KeySchema", [])]
        return Index(
            name=raw_index["IndexName"],
            column_names=col_names,
            is_unique=False,   # DynamoDB secondary indexes are never unique
            is_primary=False,
            type=index_type,   # "GSI" or "LSI"
        )

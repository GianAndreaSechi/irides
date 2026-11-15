from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from core.db_connector.interface import BaseConnector
from core.db_connector.models import Column, Instance, Schema, Table, TableDescription
from core.db_connector.models.table_details import ForeignKey, Index, PrimaryKey
from core.db_connector.sql_utils import quote_sql_string, validate_limit_offset
from loguru import logger
from ..cache_manager import CacheManager


class SQLiteConnector(BaseConnector):
    """
    A database connector for SQLite.
    """

    @staticmethod
    def get_type() -> str:
        return "sqlite"

    def __init__(self, connection_params: Dict[str, Any], cache_manager: CacheManager):
        super().__init__(connection_params, cache_manager)
        self.db_path = connection_params.get("database")
        if not self.db_path:
            logger.error("SQLite connector requires 'database' path in connection_params.")
            raise ValueError("SQLite connector requires 'database' path in connection_params.")
        self.instance_name = connection_params.get("instance_name") or self.db_path
        self._valid_instances = {self.instance_name, self.db_path}

        # Test connection in read-only mode so missing paths never create an empty file on disk
        try:
            conn = self._open_read_only()
            conn.close()
            logger.info(f"Successfully connected to SQLite database at {self.db_path}")
        except (sqlite3.Error, FileNotFoundError) as e:
            logger.exception(f"Failed to connect to SQLite database at {self.db_path}")
            raise ConnectionError(f"Failed to connect to SQLite database at {self.db_path}: {e}") from e

    def _open_read_only(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            return sqlite3.connect(":memory:")
        path_obj = Path(self.db_path)
        if not path_obj.is_file():
            raise FileNotFoundError(f"SQLite database file does not exist: {self.db_path}")
        uri_path = quote(str(path_obj.resolve()), safe="/:")
        return sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)

    def _execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Helper to execute a query and return results as list of dicts."""
        conn = None
        try:
            conn = self._open_read_only()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        except (sqlite3.Error, FileNotFoundError) as e:
            logger.exception(f"SQLite query failed: {e} - Query: {query}")
            raise RuntimeError(f"SQLite query failed: {e} - Query: {query}") from e
        finally:
            if conn:
                conn.close()

    def list_instances(self, no_cache: bool = False) -> List[Instance]:
        cache_key = f"sqlite_instances:{self.instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Instance(**d) for d in cached_data]

        instances = [Instance(name=self.instance_name, version=sqlite3.sqlite_version)]
        self.cache_manager.set_cached_data(cache_key, [i.model_dump() for i in instances])
        return instances

    def list_schemas(self, instance_name: str, no_cache: bool = False) -> List[Schema]:
        cache_key = f"sqlite_schemas:{self.db_path}:{instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Schema(**d) for d in cached_data]

        if instance_name not in self._valid_instances:
            logger.error(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")
            raise ValueError(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")
        schemas = [Schema(name="main")]
        self.cache_manager.set_cached_data(cache_key, [s.model_dump() for s in schemas])
        return schemas

    def list_tables(
        self,
        instance_name: str,
        schema_name: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        no_cache: bool = False,
    ) -> List[Table]:
        limit, offset = validate_limit_offset(limit, offset)
        cache_key = f"sqlite_tables:{self.db_path}:{instance_name}:{schema_name}:{limit}:{offset}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Table(**d) for d in cached_data]

        if instance_name not in self._valid_instances or schema_name != "main":
            logger.error("Invalid instance or schema for SQLite.")
            raise ValueError("Invalid instance or schema for SQLite.")

        query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"

        if limit is not None:
            query += f" LIMIT {limit}"
            if offset is not None:
                query += f" OFFSET {offset}"
        elif offset is not None:
            query += f" LIMIT -1 OFFSET {offset}"

        query += ";"

        rows = self._execute_query(query)
        tables = [Table(name=row["name"], schema_name=schema_name) for row in rows]
        self.cache_manager.set_cached_data(cache_key, [t.model_dump() for t in tables])
        return tables

    def describe_table(
        self, instance_name: str, schema_name: str, table_name: str, no_cache: bool = False
    ) -> TableDescription:
        cache_key = f"sqlite_describe_table:{self.db_path}:{instance_name}:{schema_name}:{table_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return TableDescription(**cached_data)

        if instance_name not in self._valid_instances or schema_name != "main":
            logger.error("Invalid instance or schema for SQLite.")
            raise ValueError("Invalid instance or schema for SQLite.")

        query = f"PRAGMA table_info({quote_sql_string(table_name)});"
        rows = self._execute_query(query)
        if not rows:
            exists = self._execute_query(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?;",
                (table_name,),
            )
            if not exists:
                raise ValueError(f"Table '{table_name}' does not exist in SQLite database '{self.db_path}'.")

        columns = []
        for row in rows:
            columns.append(
                Column(
                    name=row["name"],
                    data_type=row["type"],
                    is_nullable=bool(not row["notnull"]) and row["pk"] == 0,
                    default_value=row["dflt_value"],
                    comment=None,
                )
            )

        primary_key = self._get_primary_key_details(table_name, rows)
        foreign_keys = self._get_foreign_key_details(table_name)
        indexes = self._get_index_details(table_name)

        table_description = TableDescription(
            instance_name=instance_name,
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            indexes=indexes,
        )
        self.cache_manager.set_cached_data(cache_key, table_description.model_dump())
        return table_description

    def _get_primary_key_details(self, table_name: str, table_info_rows: List[Dict]) -> Optional[PrimaryKey]:
        pk_columns = [
            row["name"]
            for row in sorted(
                (r for r in table_info_rows if r["pk"] > 0),
                key=lambda r: r["pk"],
            )
        ]
        return PrimaryKey(column_names=pk_columns) if pk_columns else None

    def _get_foreign_key_details(self, table_name: str) -> List[ForeignKey]:
        rows = self._execute_query(f"PRAGMA foreign_key_list({quote_sql_string(table_name)});")
        foreign_keys = []
        for row in rows:
            foreign_keys.append(
                ForeignKey(
                    column_name=row["from"],
                    referenced_table=row["table"],
                    referenced_column=row["to"],
                    constraint_name=f"fk_{table_name}_{row['id']}" if "id" in row else None,
                    ordinal_position=(int(row["seq"]) + 1) if "seq" in row and row["seq"] is not None else None,
                )
            )
        return foreign_keys

    def _get_index_details(self, table_name: str) -> List[Index]:
        index_list = self._execute_query(f"PRAGMA index_list({quote_sql_string(table_name)});")
        indexes = []
        for idx in index_list:
            index_name = idx["name"]
            is_unique = bool(idx["unique"])
            is_primary = idx.get("origin") == "pk"
            col_rows = self._execute_query(f"PRAGMA index_info({quote_sql_string(index_name)});")
            col_names = [r["name"] for r in sorted(col_rows, key=lambda r: r["seqno"])]
            indexes.append(Index(
                name=index_name,
                column_names=col_names,
                is_unique=is_unique,
                is_primary=is_primary,
                type=None
            ))
        return indexes

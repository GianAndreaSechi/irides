import re
try:
    import duckdb
except ImportError:  # pragma: no cover - optional extra 'duckdb'
    duckdb = None  # type: ignore[assignment]
from typing import List, Dict, Any, Optional
from core.db_connector.interface import BaseConnector
from core.db_connector.models import Instance, Schema, Table, Column, TableDescription
from core.db_connector.models.table_details import PrimaryKey, ForeignKey, Index
from core.db_connector.sql_utils import quote_sql_string, validate_limit_offset
from loguru import logger
from ..cache_manager import CacheManager


class DuckDBConnector(BaseConnector):
    """
    A database connector for DuckDB.
    """

    @staticmethod
    def get_type() -> str:
        return "duckdb"

    def __init__(self, connection_params: Dict[str, Any], cache_manager: CacheManager):
        super().__init__(connection_params, cache_manager)
        if duckdb is None:
            raise ImportError("Missing optional dependency 'duckdb'. Install with: pip install 'irides-core[duckdb]'")
        self.database = connection_params.get("database", ":memory:")
        self.instance_name = connection_params.get("instance_name") or self.database
        self._valid_instances = {self.instance_name, self.database}

        # Test connection
        try:
            conn = self._get_connection()
            conn.close()
            logger.info(f"Successfully connected to DuckDB database at {self.database}")
        except Exception as e:
            logger.exception(f"Failed to connect to DuckDB database at {self.database}")
            raise ConnectionError(f"Failed to connect to DuckDB database at {self.database}: {e}")

    def _get_connection(self):
        """Helper to get a database connection."""
        is_memory = self.database == ":memory:"
        return duckdb.connect(database=self.database, read_only=not is_memory)

    def _execute_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Helper to execute a query and return results as list of dicts."""
        conn = None
        try:
            conn = self._get_connection()
            if params:
                result = conn.execute(query, params).fetchall()
            else:
                result = conn.execute(query).fetchall()

            columns = [desc[0] for desc in conn.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            logger.exception(f"DuckDB query failed: {e} - Query: {query}")
            raise RuntimeError(f"DuckDB query failed: {e} - Query: {query}")
        finally:
            if conn:
                conn.close()

    def list_instances(self, no_cache: bool = False) -> List[Instance]:
        cache_key = f"duckdb_instances:{self.instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Instance(**d) for d in cached_data]

        instances = [Instance(name=self.instance_name, version=duckdb.__version__)]
        self.cache_manager.set_cached_data(cache_key, [i.model_dump() for i in instances])
        return instances

    def list_schemas(self, instance_name: str, no_cache: bool = False) -> List[Schema]:
        cache_key = f"duckdb_schemas:{self.database}:{instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Schema(**d) for d in cached_data]

        if instance_name not in self._valid_instances:
            logger.error(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")
            raise ValueError(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")

        try:
            rows = self._execute_query(
                """
                SELECT DISTINCT schema_name
                FROM information_schema.schemata
                WHERE catalog_name = current_database()
                  AND schema_name NOT IN ('information_schema', 'pg_catalog')
                ORDER BY schema_name;
                """
            )
        except Exception:
            rows = self._execute_query(
                """
                SELECT DISTINCT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
                ORDER BY schema_name;
                """
            )
        schemas = [Schema(name=row["schema_name"]) for row in rows]
        if not schemas:
            schemas = [Schema(name="main")]

        self.cache_manager.set_cached_data(cache_key, [s.model_dump() for s in schemas])
        return schemas

    def list_tables(self, instance_name: str, schema_name: str, limit: Optional[int] = None, offset: Optional[int] = None, no_cache: bool = False) -> List[Table]:
        limit, offset = validate_limit_offset(limit, offset)
        cache_key = f"duckdb_tables:{self.database}:{instance_name}:{schema_name}:{limit}:{offset}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Table(**d) for d in cached_data]

        if instance_name not in self._valid_instances:
            logger.error(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")
            raise ValueError(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")

        query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = ?
        ORDER BY table_name
        """

        if limit is not None:
            query += f" LIMIT {limit}"
        if offset is not None:
            query += f" OFFSET {offset}"

        query += ";"

        rows = self._execute_query(query, (schema_name,))
        tables = [Table(name=row["table_name"], schema_name=schema_name) for row in rows]

        self.cache_manager.set_cached_data(cache_key, [t.model_dump() for t in tables])
        return tables

    def describe_table(self, instance_name: str, schema_name: str, table_name: str, no_cache: bool = False) -> TableDescription:
        cache_key = f"duckdb_describe_table:{self.database}:{instance_name}:{schema_name}:{table_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return TableDescription(**cached_data)

        if instance_name not in self._valid_instances:
            logger.error(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")
            raise ValueError(f"Instance name '{instance_name}' does not match connected database '{self.instance_name}'")

        query = f"PRAGMA table_info({quote_sql_string(f'{schema_name}.{table_name}')});"
        rows = self._execute_query(query)

        columns = []
        for row in rows:
            columns.append(
                Column(
                    name=row["name"],
                    data_type=row["type"],
                    is_nullable=not row["notnull"],
                    default_value=row["dflt_value"],
                    comment=None,
                )
            )

        primary_key = self._get_primary_key_details(schema_name, table_name)
        foreign_keys = self._get_foreign_key_details(schema_name, table_name)
        indexes = self._get_index_details(schema_name, table_name)

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

    def _get_primary_key_details(self, schema_name: str, table_name: str) -> Optional[PrimaryKey]:
        query = """
            SELECT constraint_column_names
            FROM duckdb_constraints()
            WHERE table_name = ?
              AND schema_name = ?
              AND constraint_type = 'PRIMARY KEY'
        """
        rows = self._execute_query(query, (table_name, schema_name))
        if rows:
            col_names = rows[0].get("constraint_column_names", [])
            if isinstance(col_names, list) and col_names:
                return PrimaryKey(column_names=col_names)
        return None

    def _get_foreign_key_details(self, schema_name: str, table_name: str) -> List[ForeignKey]:
        query = """
            SELECT
                constraint_name,
                constraint_column_names,
                referenced_table,
                referenced_column_names
            FROM duckdb_constraints()
            WHERE table_name = ?
              AND schema_name = ?
              AND constraint_type = 'FOREIGN KEY'
        """
        try:
            rows = self._execute_query(query, (table_name, schema_name))
            foreign_keys: List[ForeignKey] = []
            for row in rows:
                src_cols = row.get("constraint_column_names") or []
                ref_cols = row.get("referenced_column_names") or []
                ref_table = row.get("referenced_table") or ""
                cname = row.get("constraint_name")
                for pos, (src_col, ref_col) in enumerate(zip(src_cols, ref_cols), start=1):
                    foreign_keys.append(
                        ForeignKey(
                            column_name=src_col,
                            referenced_table=ref_table,
                            referenced_column=ref_col,
                            constraint_name=cname,
                            ordinal_position=pos,
                        )
                    )
            return foreign_keys
        except Exception:
            fallback_query = """
                SELECT
                    kcu.column_name,
                    ccu.table_name AS referenced_table,
                    ccu.column_name AS referenced_column,
                    tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    AND tc.table_name = kcu.table_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_name = ?
                  AND tc.table_schema = ?
            """
            rows = self._execute_query(fallback_query, (table_name, schema_name))
            return [
                ForeignKey(
                    column_name=row["column_name"],
                    referenced_table=row["referenced_table"],
                    referenced_column=row["referenced_column"],
                    constraint_name=row["constraint_name"],
                )
                for row in rows
            ]

    def _get_index_details(self, schema_name: str, table_name: str) -> List[Index]:
        query = """
            SELECT index_name, is_unique, is_primary, sql
            FROM duckdb_indexes()
            WHERE table_name = ?
              AND schema_name = ?
        """
        rows = self._execute_query(query, (table_name, schema_name))
        indexes = []
        for row in rows:
            col_names = []
            if row.get('sql'):
                match = re.search(r'\(([^)]+)\)', row['sql'])
                if match:
                    col_names = [c.strip() for c in match.group(1).split(',')]
            indexes.append(Index(
                name=row['index_name'],
                column_names=col_names,
                is_unique=bool(row['is_unique']),
                is_primary=bool(row.get('is_primary', False)),
                type=None
            ))
        return indexes

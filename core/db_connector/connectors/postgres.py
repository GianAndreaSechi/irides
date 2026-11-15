import psycopg2
import psycopg2.pool
import psycopg2.extras
import hashlib
from typing import List, Dict, Any, Optional
from core.db_connector.interface import BaseConnector
from core.db_connector.models import Instance, Schema, Table, Column, PrimaryKey, ForeignKey, Index, TableDescription
from core.db_connector.models.table_details import Partition
from core.db_connector.sql_utils import validate_limit_offset
from loguru import logger
from ..cache_manager import CacheManager


class PostgreSQLConnector(BaseConnector):
    """
    A database connector for PostgreSQL.

    Hierarchy mapping:
        instance  = host  (the pg server)
        schema    = PostgreSQL schema namespace (e.g. "public")
        table     = table

    The target database is fixed in connection_params.

    Connection params:
        - host (str): required.
        - port (int): default 5432.
        - user (str): required.
        - password (str): required.
        - database (str): required — the PostgreSQL database to connect to.
        - pool_size (int): default 5.

    Partition keys are detected for declaratively partitioned tables (PG 10+).
    """

    _pools: Dict[str, psycopg2.pool.ThreadedConnectionPool] = {}

    @staticmethod
    def get_type() -> str:
        return "postgres"

    def __init__(self, connection_params: Dict[str, Any], cache_manager: CacheManager):
        super().__init__(connection_params, cache_manager)

        self.host = connection_params.get("host")
        self.port = int(connection_params.get("port", 5432))
        self.user = connection_params.get("user")
        self.password = connection_params.get("password")
        self.database = connection_params.get("database")
        pool_size = int(connection_params.get("pool_size", 5))

        if not (self.host and self.user and self.password is not None and self.database):
            raise ValueError(
                "PostgreSQL connector requires 'host', 'user', 'password', and 'database' in connection_params."
            )

        password_fingerprint = hashlib.sha256((self.password or "").encode()).hexdigest()[:12]
        self._auth_fingerprint = hashlib.sha256(f"{self.user}:{password_fingerprint}".encode()).hexdigest()[:12]
        pool_key = f"{self.host}:{self.port}:{self.user}:{self.database}:{password_fingerprint}"
        if pool_key not in PostgreSQLConnector._pools:
            try:
                PostgreSQLConnector._pools[pool_key] = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=pool_size,
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    dbname=self.database,
                )
                logger.info(f"Created connection pool for PostgreSQL at {self.host}:{self.port}/{self.database}")
            except psycopg2.Error as e:
                logger.exception(f"Failed to create connection pool for PostgreSQL at {self.host}:{self.port}")
                raise ConnectionError(f"Failed to connect to PostgreSQL at {self.host}:{self.port}: {e}")
        else:
            logger.info(f"Reusing existing connection pool for PostgreSQL at {self.host}:{self.port}/{self.database}")

        self.pool = PostgreSQLConnector._pools[pool_key]

    def _execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        conn = None
        try:
            conn = self.pool.getconn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except psycopg2.Error as e:
            logger.exception(f"PostgreSQL query failed: {e} — Query: {query}")
            raise RuntimeError(f"PostgreSQL query failed: {e} — Query: {query}")
        finally:
            if conn:
                conn.rollback()
                self.pool.putconn(conn)

    def _cache_scope(self) -> str:
        auth = getattr(self, "_auth_fingerprint", "")
        return f"{self.host}:{self.port}:{self.database}:{auth}" if auth else f"{self.host}:{self.port}:{self.database}"

    # ------------------------------------------------------------------
    # list_instances  →  the server host + version
    # ------------------------------------------------------------------

    def list_instances(self, no_cache: bool = False) -> List[Instance]:
        cache_key = f"postgres_instances:{self._cache_scope()}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Instance(**d) for d in cached_data]

        rows = self._execute_query("SELECT version();")
        version = rows[0]["version"] if rows else None
        instances = [Instance(name=self.host, version=version)]
        self.cache_manager.set_cached_data(cache_key, [i.model_dump() for i in instances])
        return instances

    # ------------------------------------------------------------------
    # list_schemas  →  PostgreSQL schemas (namespaces) in the database
    # ------------------------------------------------------------------

    def list_schemas(self, instance_name: str, no_cache: bool = False) -> List[Schema]:
        cache_key = f"postgres_schemas:{self._cache_scope()}:{instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Schema(**d) for d in cached_data]

        if instance_name != self.host:
            raise ValueError(f"Instance name '{instance_name}' does not match connected host '{self.host}'")

        rows = self._execute_query("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name;
        """)
        schemas = [Schema(name=row["schema_name"]) for row in rows]
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
        cache_key = f"postgres_tables:{self._cache_scope()}:{instance_name}:{schema_name}:{limit}:{offset}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Table(**d) for d in cached_data]

        if instance_name != self.host:
            raise ValueError(f"Instance name '{instance_name}' does not match connected host '{self.host}'")

        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        if offset is not None:
            query += f" OFFSET {offset}"

        rows = self._execute_query(query, (schema_name,))
        tables = [Table(name=row["table_name"], schema_name=schema_name) for row in rows]
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
        cache_key = f"postgres_describe_table:{self._cache_scope()}:{instance_name}:{schema_name}:{table_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return TableDescription(**cached_data)

        if instance_name != self.host:
            raise ValueError(f"Instance name '{instance_name}' does not match connected host '{self.host}'")

        col_rows = self._execute_query("""
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                pgd.description AS comment
            FROM information_schema.columns c
            LEFT JOIN pg_catalog.pg_statio_all_tables st
                ON st.schemaname = c.table_schema AND st.relname = c.table_name
            LEFT JOIN pg_catalog.pg_description pgd
                ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
            WHERE c.table_schema = %s
              AND c.table_name   = %s
            ORDER BY c.ordinal_position;
        """, (schema_name, table_name))

        columns = [
            Column(
                name=row["column_name"],
                data_type=row["data_type"],
                is_nullable=(row["is_nullable"] == "YES"),
                default_value=row["column_default"],
                comment=row.get("comment"),
            )
            for row in col_rows
        ]

        primary_key = self._get_primary_key_details(schema_name, table_name)
        foreign_keys = self._get_foreign_key_details(schema_name, table_name)
        indexes = self._get_index_details(schema_name, table_name)
        partitions = self._get_partition_details(schema_name, table_name)

        table_description = TableDescription(
            instance_name=instance_name,
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            indexes=indexes,
            partitions=partitions,
        )
        self.cache_manager.set_cached_data(cache_key, table_description.model_dump())
        return table_description

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_primary_key_details(self, schema_name: str, table_name: str) -> Optional[PrimaryKey]:
        rows = self._execute_query("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema    = kcu.table_schema
               AND tc.table_name      = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema    = %s
              AND tc.table_name      = %s
            ORDER BY kcu.ordinal_position;
        """, (schema_name, table_name))
        if rows:
            return PrimaryKey(column_names=[r["column_name"] for r in rows])
        return None

    def _get_foreign_key_details(self, schema_name: str, table_name: str) -> List[ForeignKey]:
        rows = self._execute_query("""
            SELECT
                kcu.column_name,
                ccu.table_schema AS referenced_schema,
                ccu.table_name   AS referenced_table,
                ccu.column_name  AS referenced_column,
                tc.constraint_name,
                kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_catalog = kcu.constraint_catalog
               AND tc.constraint_schema  = kcu.constraint_schema
               AND tc.constraint_name    = kcu.constraint_name
               AND tc.table_schema       = kcu.table_schema
               AND tc.table_name         = kcu.table_name
            JOIN information_schema.referential_constraints rc
                ON tc.constraint_catalog = rc.constraint_catalog
               AND tc.constraint_schema  = rc.constraint_schema
               AND tc.constraint_name    = rc.constraint_name
            JOIN information_schema.key_column_usage ccu
                ON rc.unique_constraint_catalog = ccu.constraint_catalog
               AND rc.unique_constraint_schema  = ccu.constraint_schema
               AND rc.unique_constraint_name    = ccu.constraint_name
               AND kcu.position_in_unique_constraint = ccu.ordinal_position
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema    = %s
              AND tc.table_name      = %s
            ORDER BY tc.constraint_name, kcu.ordinal_position;
        """, (schema_name, table_name))
        return [
            ForeignKey(
                column_name=r["column_name"],
                referenced_schema=r.get("referenced_schema"),
                referenced_table=r["referenced_table"],
                referenced_column=r["referenced_column"],
                constraint_name=r["constraint_name"],
                ordinal_position=r.get("ordinal_position"),
            )
            for r in rows
        ]

    def _get_index_details(self, schema_name: str, table_name: str) -> List[Index]:
        rows = self._execute_query("""
            SELECT
                i.relname                          AS index_name,
                ix.indisunique                     AS is_unique,
                ix.indisprimary                    AS is_primary,
                am.amname                          AS index_type,
                array_agg(a.attname ORDER BY u.pos) AS column_names
            FROM pg_catalog.pg_index ix
            JOIN pg_catalog.pg_class  t  ON t.oid  = ix.indrelid
            JOIN pg_catalog.pg_class  i  ON i.oid  = ix.indexrelid
            JOIN pg_catalog.pg_am     am ON am.oid = i.relam
            JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
            JOIN unnest(ix.indkey) WITH ORDINALITY AS u(attnum, pos) ON true
            JOIN pg_catalog.pg_attribute a
                ON a.attrelid = t.oid AND a.attnum = u.attnum
            WHERE n.nspname = %s
              AND t.relname = %s
            GROUP BY i.relname, ix.indisunique, ix.indisprimary, am.amname;
        """, (schema_name, table_name))
        return [
            Index(
                name=r["index_name"],
                column_names=list(r["column_names"]),
                is_unique=bool(r["is_unique"]),
                is_primary=bool(r["is_primary"]),
                type=r["index_type"],
            )
            for r in rows
        ]

    def _get_partition_details(self, schema_name: str, table_name: str) -> List[Partition]:
        """Returns partition key columns for declaratively partitioned tables (PG 10+)."""
        rows = self._execute_query("""
            SELECT
                a.attname                                          AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod)   AS data_type,
                col_description(c.oid, a.attnum)                   AS comment
            FROM pg_catalog.pg_partitioned_table pt
            JOIN pg_catalog.pg_class c ON c.oid = pt.partrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN unnest(pt.partattrs) WITH ORDINALITY AS u(attnum, pos) ON true
            JOIN pg_catalog.pg_attribute a
                ON a.attrelid = c.oid AND a.attnum = u.attnum
            WHERE n.nspname = %s
              AND c.relname = %s
            ORDER BY u.pos;
        """, (schema_name, table_name))
        return [
            Partition(
                column_name=r["column_name"],
                data_type=r["data_type"],
                comment=r.get("comment"),
            )
            for r in rows
        ]

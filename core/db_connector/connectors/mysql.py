import re
import hashlib
import mysql.connector
import mysql.connector.pooling
from typing import Dict, Any, List, Optional
from core.db_connector.interface import BaseConnector
from core.db_connector.models import Instance, Schema, Table, Column, PrimaryKey, ForeignKey, Index, TableDescription
from core.db_connector.sql_utils import quote_identifier, validate_limit_offset
from loguru import logger
from ..cache_manager import CacheManager

class MySQLConnector(BaseConnector):
    """
    A database connector for MySQL.
    """

    _pools: Dict[str, mysql.connector.pooling.MySQLConnectionPool] = {}

    @staticmethod
    def get_type() -> str:
        return "mysql"

    def __init__(self, connection_params: Dict[str, Any], cache_manager: CacheManager):
        super().__init__(connection_params, cache_manager)
        self.host = connection_params.get("host")
        self.user = connection_params.get("user")
        self.password = connection_params.get("password")
        self.port = connection_params.get("port", 3306)
        pool_size = connection_params.get("pool_size", 5)

        if not (self.host and self.user and self.password is not None):
            logger.error("MySQL connector requires 'host', 'user', and 'password' in connection_params.")
            raise ValueError("MySQL connector requires 'host', 'user', and 'password' in connection_params.")

        password_fingerprint = hashlib.sha256((self.password or "").encode()).hexdigest()[:12]
        pool_key = f"{self.host}:{self.port}:{self.user}:{password_fingerprint}"
        if pool_key not in MySQLConnector._pools:
            try:
                pool_name = re.sub(
                    r'[^a-zA-Z0-9_]',
                    '_',
                    f"mysql_{self.host}_{self.port}_{self.user}_{password_fingerprint}",
                )[:64]
                MySQLConnector._pools[pool_key] = mysql.connector.pooling.MySQLConnectionPool(
                    pool_name=pool_name,
                    pool_size=pool_size,
                    pool_reset_session=True,
                    host=self.host,
                    user=self.user,
                    password=self.password,
                    port=self.port
                )
                logger.info(f"Created connection pool for MySQL at {self.host}:{self.port} (size: {pool_size})")
            except mysql.connector.Error as e:
                logger.exception(f"Failed to create connection pool for MySQL at {self.host}:{self.port}")
                raise ConnectionError(f"Failed to connect to MySQL database at {self.host}:{self.port}: {e}")
        else:
            logger.info(f"Reusing existing connection pool for MySQL at {self.host}:{self.port}")

        self.pool = MySQLConnector._pools[pool_key]

    def _get_connection(self, database: Optional[str] = None):
        """Helper to get a connection from the pool."""
        conn = self.pool.get_connection()
        if database:
            conn.database = database
        return conn

    def _execute_query(self, query: str, params: tuple = (), database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Helper to execute a query and return results as list of dicts."""
        conn = None
        cursor = None
        try:
            conn = self._get_connection(database=database)
            cursor = conn.cursor(dictionary=True) # Return rows as dicts
            cursor.execute(query, params)
            return cursor.fetchall()
        except mysql.connector.Error as e:
            logger.exception(f"MySQL query failed: {e} - Query: {query}")
            raise RuntimeError(f"MySQL query failed: {e} - Query: {query}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def list_instances(self, no_cache: bool = False) -> List[Instance]:
        cache_key = f"mysql_instances:{self.host}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Instance(**d) for d in cached_data]

        # For MySQL, the instance is the host. We can get the version.
        query = "SELECT VERSION();"
        result = self._execute_query(query)
        version = result[0]['VERSION()'] if result else None
        instances = [Instance(name=self.host, version=version)]
        self.cache_manager.set_cached_data(cache_key, [i.model_dump() for i in instances])
        return instances

    def list_schemas(self, instance_name: str, no_cache: bool = False) -> List[Schema]:
        cache_key = f"mysql_schemas:{self.host}:{instance_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Schema(**d) for d in cached_data]

        if instance_name != self.host:
            logger.error(f"Instance name '{instance_name}' does not match connected host '{self.host}'")
            raise ValueError(f"Instance name '{instance_name}' does not match connected host '{self.host}'")
        
        query = "SHOW DATABASES;"
        rows = self._execute_query(query)
        schemas = [Schema(name=row["Database"]) for row in rows if row["Database"] not in ["information_schema", "mysql", "performance_schema", "sys"]]
        self.cache_manager.set_cached_data(cache_key, [s.model_dump() for s in schemas])
        return schemas

    def list_tables(self, instance_name: str, schema_name: str, limit: Optional[int] = None, offset: Optional[int] = None, no_cache: bool = False) -> List[Table]:
        limit, offset = validate_limit_offset(limit, offset)
        cache_key = f"mysql_tables:{self.host}:{instance_name}:{schema_name}:{limit}:{offset}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return [Table(**d) for d in cached_data]

        if instance_name != self.host:
            logger.error(f"Instance name '{instance_name}' does not match connected host '{self.host}'")
            raise ValueError(f"Instance name '{instance_name}' does not match connected host '{self.host}'")
        
        query = (
            "SELECT TABLE_NAME "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s "
            "ORDER BY TABLE_NAME"
        )
        params: list[Any] = [schema_name]
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
            if offset is not None:
                query += " OFFSET %s"
                params.append(offset)
        elif offset is not None:
            query += " LIMIT 18446744073709551615 OFFSET %s"
            params.append(offset)

        query += ";"

        rows = self._execute_query(query, tuple(params), database="information_schema")
        tables = [Table(name=row["TABLE_NAME"], schema_name=schema_name) for row in rows]
        self.cache_manager.set_cached_data(cache_key, [t.model_dump() for t in tables])
        return tables

    def describe_table(self, instance_name: str, schema_name: str, table_name: str, no_cache: bool = False) -> TableDescription:
        cache_key = f"mysql_describe_table:{self.host}:{instance_name}:{schema_name}:{table_name}"
        cached_data = self.cache_manager.get_cached_data(cache_key, no_cache)
        if cached_data:
            return TableDescription(**cached_data)

        if instance_name != self.host:
            logger.error(f"Instance name '{instance_name}' does not match connected host '{self.host}'")
            raise ValueError(f"Instance name '{instance_name}' does not match connected host '{self.host}'")
        
        # Fetch columns
        query_columns = (
            f"SHOW COLUMNS FROM {quote_identifier(schema_name, '`')}."
            f"{quote_identifier(table_name, '`')};"
        )
        column_rows = self._execute_query(query_columns, database=schema_name)
        
        columns = []
        for row in column_rows:
            columns.append(
                Column(
                    name=row["Field"],
                    data_type=row["Type"],
                    is_nullable=row["Null"] == "YES",
                    default_value=row["Default"],
                    comment=None
                )
            )
        
        # Fetch PK, FK, Indexes
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
            indexes=indexes
        )
        self.cache_manager.set_cached_data(cache_key, table_description.model_dump())
        return table_description

    def _get_primary_key_details(self, schema_name: str, table_name: str) -> Optional[PrimaryKey]:
        query = """
            SELECT COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY ORDINAL_POSITION;
        """
        rows = self._execute_query(query, (schema_name, table_name), database='information_schema')
        if rows:
            return PrimaryKey(column_names=[row['COLUMN_NAME'] for row in rows])
        return None

    def _get_foreign_key_details(self, schema_name: str, table_name: str) -> List[ForeignKey]:
        query = """
            SELECT
                kcu.COLUMN_NAME,
                kcu.REFERENCED_TABLE_NAME,
                kcu.REFERENCED_COLUMN_NAME,
                kcu.CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE AS kcu
            WHERE kcu.TABLE_SCHEMA = %s
              AND kcu.TABLE_NAME = %s
              AND kcu.REFERENCED_TABLE_NAME IS NOT NULL;
        """
        rows = self._execute_query(query, (schema_name, table_name), database='information_schema')
        foreign_keys = []
        for row in rows:
            foreign_keys.append(
                ForeignKey(
                    column_name=row['COLUMN_NAME'],
                    referenced_table=row['REFERENCED_TABLE_NAME'],
                    referenced_column=row['REFERENCED_COLUMN_NAME'],
                    constraint_name=row['CONSTRAINT_NAME']
                )
            )
        return foreign_keys

    def _get_index_details(self, schema_name: str, table_name: str) -> List[Index]:
        query = """
            SELECT
                INDEX_NAME,
                COLUMN_NAME,
                NON_UNIQUE,
                SEQ_IN_INDEX
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            ORDER BY INDEX_NAME, SEQ_IN_INDEX;
        """
        rows = self._execute_query(query, (schema_name, table_name), database='information_schema')
        
        indexes_map = {}
        for row in rows:
            index_name = row['INDEX_NAME']
            if index_name not in indexes_map:
                indexes_map[index_name] = {
                    'name': index_name,
                    'column_names': [],
                    'is_unique': not bool(row['NON_UNIQUE']),
                    'is_primary': (index_name == 'PRIMARY'),
                    'type': None # information_schema.STATISTICS doesn't directly give index type (BTREE/HASH)
                }
            if row['COLUMN_NAME'] is not None:
                indexes_map[index_name]['column_names'].append(row['COLUMN_NAME'])

        
        return [Index(**idx) for idx in indexes_map.values()]

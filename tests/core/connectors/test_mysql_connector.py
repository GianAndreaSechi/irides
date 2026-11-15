import pytest
import os

pytest.importorskip("mysql.connector")

from core.db_connector.connectors.mysql import MySQLConnector
from core.db_connector.models import TableDescription
from loguru import logger


class DummyCacheManager:
    def get_cached_data(self, key, no_cache=False):
        return None

    def set_cached_data(self, key, data, ttl=None):
        pass

# --- Configuration for MySQL Test (ADJUST THESE VALUES) ---
# For a real test, you would need a running MySQL instance.
# Consider using Docker for a temporary test database.
MYSQL_TEST_CONFIG = {
    "host": os.getenv("MYSQL_TEST_HOST"),
    "user": os.getenv("MYSQL_TEST_USER"),
    "password": os.getenv("MYSQL_TEST_PASSWORD", ""),
    "port": int(os.getenv("MYSQL_TEST_PORT", 3306)),
    # "database": "test_db" # Optional, for specific database operations
}
# ----------------------------------------------------------

MYSQL_IS_CONFIGURED = bool(MYSQL_TEST_CONFIG["host"] and MYSQL_TEST_CONFIG["user"])
mysql_skip_reason = "Set MYSQL_TEST_HOST and MYSQL_TEST_USER to run MySQL integration tests."
pytestmark = pytest.mark.skipif(not MYSQL_IS_CONFIGURED, reason=mysql_skip_reason)

@pytest.fixture(scope="module")
def mysql_connector():
    """Fixture to provide an initialized MySQLConnector."""
    # Ensure a test database exists and has some data for testing
    # This part would typically be handled by a setup script or Docker compose
    # For this example, we assume 'test_db' exists and has 'test_table'
    
    # Example setup for a test database and table:
    # CREATE DATABASE IF NOT EXISTS test_db;
    # USE test_db;
    # CREATE TABLE IF NOT EXISTS test_table (
    #     id INT AUTO_INCREMENT PRIMARY KEY,
    #     name VARCHAR(255) NOT NULL,
    #     value INT
    # );
    # INSERT INTO test_table (name, value) VALUES ('item1', 10), ('item2', 20);

    try:
        connector = MySQLConnector(
            connection_params=MYSQL_TEST_CONFIG,
            cache_manager=DummyCacheManager(),
        )
    except (ValueError, ConnectionError) as e:
        logger.error(f"MySQL test skipped: {e}")
        pytest.skip(f"MySQL connection unavailable: {e}")
    yield connector
    # Teardown (optional): clean up test data or drop test database
    # For simplicity, not implemented here.

def test_mysql_get_type():
    assert MySQLConnector.get_type() == "mysql"

def test_mysql_list_instances(mysql_connector):
    instances = mysql_connector.list_instances()
    assert len(instances) == 1
    assert instances[0].name == MYSQL_TEST_CONFIG["host"]
    assert instances[0].version is not None

def test_mysql_list_schemas(mysql_connector):
    schemas = mysql_connector.list_schemas(instance_name=MYSQL_TEST_CONFIG["host"])
    # Assert that 'test_db' (or your chosen test database) is in the list
    assert any(s.name == "test_db" for s in schemas)

def test_mysql_list_tables(mysql_connector):
    tables = mysql_connector.list_tables(
        instance_name=MYSQL_TEST_CONFIG["host"], schema_name="test_db"
    )
    assert any(t.name == "test_table" for t in tables)
    assert all(t.schema_name == "test_db" for t in tables)

def test_mysql_describe_table(mysql_connector):
    # Note: describe_table now returns TableDescription, not List[Column]
    table_desc: TableDescription = mysql_connector.describe_table(
        instance_name=MYSQL_TEST_CONFIG["host"], schema_name="test_db", table_name="test_table"
    )
    
    # Assertions for columns
    assert len(table_desc.columns) == 3 # id, name, value
    col_names = {c.name for c in table_desc.columns}
    assert "id" in col_names
    assert "name" in col_names
    assert "value" in col_names

    id_col = next(c for c in table_desc.columns if c.name == "id")
    assert id_col.data_type == "int(11)"
    assert not id_col.is_nullable

    name_col = next(c for c in table_desc.columns if c.name == "name")
    assert name_col.data_type == "varchar(255)"
    assert not name_col.is_nullable

    value_col = next(c for c in table_desc.columns if c.name == "value")
    assert value_col.data_type == "int(11)"
    assert value_col.is_nullable # Assuming default INT is nullable

    # Assertions for PK, FK, Indexes (basic checks)
    assert table_desc.primary_key is not None
    assert "id" in table_desc.primary_key.column_names
    
    # Assuming no FKs or other indexes for this basic test table
    assert len(table_desc.foreign_keys) == 0
    # Check for primary key index
    pk_index = next((idx for idx in table_desc.indexes if idx.is_primary), None)
    assert pk_index is not None
    assert pk_index.name == "PRIMARY"
    assert "id" in pk_index.column_names
    assert pk_index.is_unique

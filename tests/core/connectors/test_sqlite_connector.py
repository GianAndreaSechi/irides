import pytest
import sqlite3
from core.db_connector.connectors.sqlite import SQLiteConnector
from loguru import logger


class DummyCacheManager:
    def get_cached_data(self, key, no_cache=False):
        return None

    def set_cached_data(self, key, data, ttl=None):
        pass

@pytest.fixture
def sqlite_db_path(tmp_path):
    """Fixture to create a temporary SQLite database file."""
    db_file = tmp_path / "test_database.db"
    logger.info(f"Creating temporary SQLite database at: {db_file}")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE
        );
    """)
    cursor.execute("INSERT INTO users (name, email) VALUES ('Alice', 'alice@example.com');")
    cursor.execute("INSERT INTO users (name, email) VALUES ('Bob', 'bob@example.com');")

    cursor.execute("""
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            price REAL
        );
    """)
    cursor.execute("INSERT INTO products (product_name, price) VALUES ('Laptop', 1200.00);")

    conn.commit()
    conn.close()
    return str(db_file)

@pytest.fixture
def sqlite_connector(sqlite_db_path):
    """Fixture to provide an initialized SQLiteConnector."""
    logger.info(f"Initializing SQLiteConnector for database: {sqlite_db_path}")
    return SQLiteConnector(
        connection_params={"database": sqlite_db_path},
        cache_manager=DummyCacheManager(),
    )

def test_sqlite_get_type():
    assert SQLiteConnector.get_type() == "sqlite"

def test_sqlite_list_instances(sqlite_connector, sqlite_db_path):
    instances = sqlite_connector.list_instances()
    assert len(instances) == 1
    assert instances[0].name == sqlite_db_path
    assert instances[0].version is not None # Check if version is populated

def test_sqlite_list_schemas(sqlite_connector, sqlite_db_path):
    schemas = sqlite_connector.list_schemas(instance_name=sqlite_db_path)
    assert len(schemas) == 1
    assert schemas[0].name == "main"

def test_sqlite_list_tables(sqlite_connector, sqlite_db_path):
    tables = sqlite_connector.list_tables(instance_name=sqlite_db_path, schema_name="main")
    assert len(tables) == 2
    table_names = {t.name for t in tables}
    assert "users" in table_names
    assert "products" in table_names
    # Check if schema_name is correctly populated
    assert all(t.schema_name == "main" for t in tables)

def test_sqlite_describe_table_users(sqlite_connector, sqlite_db_path):
    table_desc = sqlite_connector.describe_table(
        instance_name=sqlite_db_path, schema_name="main", table_name="users"
    )
    columns = table_desc.columns
    assert len(columns) == 3
    
    col_names = {c.name for c in columns}
    assert "id" in col_names
    assert "name" in col_names
    assert "email" in col_names

    id_col = next(c for c in columns if c.name == "id")
    assert id_col.data_type == "INTEGER"
    assert not id_col.is_nullable

    name_col = next(c for c in columns if c.name == "name")
    assert name_col.data_type == "TEXT"
    assert not name_col.is_nullable

    email_col = next(c for c in columns if c.name == "email")
    assert email_col.data_type == "TEXT"
    assert email_col.is_nullable # UNIQUE constraint doesn't imply NOT NULL unless specified

def test_sqlite_describe_table_products(sqlite_connector, sqlite_db_path):
    table_desc = sqlite_connector.describe_table(
        instance_name=sqlite_db_path, schema_name="main", table_name="products"
    )
    columns = table_desc.columns
    assert len(columns) == 3
    
    col_names = {c.name for c in columns}
    assert "product_id" in col_names
    assert "product_name" in col_names
    assert "price" in col_names

    product_id_col = next(c for c in columns if c.name == "product_id")
    assert product_id_col.data_type == "INTEGER"
    assert not product_id_col.is_nullable

    product_name_col = next(c for c in columns if c.name == "product_name")
    assert product_name_col.data_type == "TEXT"
    assert not product_name_col.is_nullable

    price_col = next(c for c in columns if c.name == "price")
    assert price_col.data_type == "REAL"
    assert price_col.is_nullable # Default for REAL is nullable


def test_sqlite_missing_database_file_raises_without_creating_file(tmp_path):
    missing_path = tmp_path / "does_not_exist.sqlite"
    with pytest.raises(ConnectionError, match="does not exist"):
        SQLiteConnector(
            connection_params={"database": str(missing_path)},
            cache_manager=DummyCacheManager(),
        )
    assert not missing_path.exists()


def test_sqlite_list_tables_offset_without_limit(sqlite_connector, sqlite_db_path):
    tables = sqlite_connector.list_tables(
        instance_name=sqlite_db_path, schema_name="main", offset=1
    )
    assert len(tables) == 1
    assert tables[0].name == "users"


def test_sqlite_describe_nonexistent_table_raises(sqlite_connector, sqlite_db_path):
    with pytest.raises(ValueError, match="does not exist"):
        sqlite_connector.describe_table(
            instance_name=sqlite_db_path, schema_name="main", table_name="no_such_table"
        )

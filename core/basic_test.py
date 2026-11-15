import sys

from core.db_connector.cache_manager import CacheManager
from core.db_connector.models import TableDescription
from loguru import logger

__test__ = False

# Configuration for MySQL Test (ADJUST THESE VALUES)
MYSQL_CONFIG = {
    "host": "<your_mysql_host>",  # e.g., "localhost" or "mysql_test_container"
    "user": "<your_mysql_user>",  # e.g., "root"
    "password": "<your_mysql_password>",  # e.g., "password"
    "port": 3306,
    # "database": "test_db" # Optional, for specific database operations
}

def run_basic_mysql_test():
    from core.db_connector.connectors.mysql import MySQLConnector

    logger.info("--- Running Basic MySQL Test ---")
    connector = None
    try:
        cache_manager = CacheManager()
        connector = MySQLConnector(connection_params=MYSQL_CONFIG, cache_manager=cache_manager)
        logger.info("MySQL connection successful!")

        logger.info("\n--- Listing Instances ---")
        instances = connector.list_instances()
        for instance in instances:
            logger.info(f"Instance: {instance.name} (Version: {instance.version})")

            logger.info(f"\n--- Listing Schemas for Instance: {instance.name} ---")
            schemas = connector.list_schemas(instance_name=instance.name)
            for schema in schemas:
                logger.info(f"  Schema: {schema.name}")

                logger.info(f"\n  --- Listing Tables for Schema: {schema.name} ---")
                tables = connector.list_tables(instance_name=instance.name, schema_name=schema.name)
                if not tables:
                    logger.info(f"    No tables found in schema: {schema.name}")
                for table in tables:
                    logger.info(f"    Table: {table.name}")

                    logger.info(f"\n      --- Describing Table: {table.name} in Schema: {schema.name} ---")
                    table_desc: TableDescription = connector.describe_table(instance_name=instance.name, schema_name=schema.name, table_name=table.name)
                    
                    logger.info(f"        Columns:")
                    if not table_desc.columns:
                        logger.info(f"          No columns found for table: {table.name}")
                    for col in table_desc.columns:
                        logger.info(f"          - Name: {col.name}, Type: {col.data_type}, Nullable: {col.is_nullable}, Default: {col.default_value}")
                    
                    if table_desc.primary_key:
                        logger.info(f"        Primary Key: {', '.join(table_desc.primary_key.column_names)}")
                    
                    if table_desc.foreign_keys:
                        logger.info(f"        Foreign Keys:")
                        for fk in table_desc.foreign_keys:
                            logger.info(f"          - Column: {fk.column_name} -> {fk.referenced_table}.{fk.referenced_column} (Constraint: {fk.constraint_name})")
                    
                    if table_desc.indexes:
                        logger.info(f"        Indexes:")
                        for idx in table_desc.indexes:
                            logger.info(f"          - Name: {idx.name}, Columns: {', '.join(idx.column_names)}, Unique: {idx.is_unique}, Primary: {idx.is_primary}, Type: {idx.type}")
                    
                    logger.info("-" * 40) # Separator for readability

    except ConnectionError as e:
        logger.error(f"MySQL connection failed: {e}")
        logger.exception("Connection Error Traceback:")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        logger.exception("Unexpected Error Traceback:")
        sys.exit(1)
    finally:
        pass

if __name__ == "__main__":
    run_basic_mysql_test()

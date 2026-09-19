# core/db_connector/connectors/__init__.py
# This file makes the connectors directory a Python package.

__all__ = ["MySQLConnector", "SQLiteConnector", "DuckDBConnector"]

try:
    from .mysql import MySQLConnector
except ImportError:
    MySQLConnector = None

try:
    from .sqlite import SQLiteConnector
except ImportError:
    SQLiteConnector = None

try:
    from .duckdb import DuckDBConnector
except ImportError:
    DuckDBConnector = None
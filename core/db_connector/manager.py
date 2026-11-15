import importlib
from pathlib import Path
import pkgutil
from typing import Dict, Optional, Type
from loguru import logger
from .cache_manager import CacheManager, NullCacheManager
from .interface import BaseConnector

_BUILTIN_CONNECTOR_MODULES = (
    "athena",
    "duckdb",
    "dynamodb",
    "mongodb",
    "mysql",
    "postgres",
    "sqlite",
    "trino",
)

CONNECTOR_EXTRA_MAP: Dict[str, str] = {
    "mysql": "mysql",
    "postgres": "postgres",
    "mongodb": "mongo",
    "trino": "trino",
    "presto": "trino",
    "athena": "aws",
    "dynamodb": "aws",
    "duckdb": "duckdb",
    "sqlite": "sqlite",
}


class ConnectorManager:
    """
    Discovers and manages available database connectors.
    """

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.connectors: Dict[str, Type[BaseConnector]] = {}
        self._missing_connectors: Dict[str, str] = {}
        self.cache_manager: CacheManager = (
            cache_manager if cache_manager is not None else NullCacheManager()
        )
        self._discover_connectors()

    def register_connector(self, connector_type: str, connector_cls: Type[BaseConnector]) -> None:
        """Publicly register a custom connector implementation."""
        if not (isinstance(connector_cls, type) and issubclass(connector_cls, BaseConnector)):
            raise TypeError("connector_cls must be a subclass of BaseConnector.")
        self.connectors[connector_type.lower()] = connector_cls

    def _discover_connectors(self) -> None:
        """
        Dynamically imports all connector modules from the 'connectors' package
        and registers the connector classes. Connectors with missing optional
        dependencies are skipped and recorded.
        """
        import core.db_connector.connectors as connectors_package

        search_paths = list(getattr(connectors_package, "__path__", []) or [])
        pkg_file = getattr(connectors_package, "__file__", None)
        if pkg_file:
            pkg_dir = str(Path(pkg_file).resolve().parent)
            if pkg_dir not in search_paths:
                search_paths.append(pkg_dir)

        module_names = set(_BUILTIN_CONNECTOR_MODULES)
        if search_paths:
            for _, discovered_name, _ in pkgutil.iter_modules(search_paths):
                module_names.add(discovered_name)

        for name in sorted(module_names):
            try:
                module = importlib.import_module(f"{connectors_package.__name__}.{name}")
            except ImportError as e:
                logger.debug(f"Connector module '{name}' skipped (missing optional dependencies: {e})")
                self._missing_connectors[name] = str(e)
                if name == "trino":
                    self._missing_connectors["presto"] = str(e)
                continue

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseConnector)
                    and attr is not BaseConnector
                ):
                    connector_type = attr.get_type()
                    try:
                        # Check if module skipped an optional library via soft-import
                        if getattr(module, "boto3", True) is None and connector_type in {"athena", "dynamodb"}:
                            self._missing_connectors[connector_type] = "No module named 'boto3'"
                            continue
                        if getattr(module, "duckdb", True) is None and connector_type == "duckdb":
                            self._missing_connectors[connector_type] = "No module named 'duckdb'"
                            continue
                    except Exception:
                        pass
                    if connector_type in self.connectors:
                        logger.warning(f"Duplicate connector type '{connector_type}' found. Overwriting.")
                    self.connectors[connector_type] = attr

    def get_available_connectors(self) -> list[str]:
        """Returns a list of available connector types."""
        return list(self.connectors.keys())

    def get_connector(self, connector_type: str, connection_params: dict) -> BaseConnector:
        """
        Initializes and returns a connector instance of the specified type.

        Args:
            connector_type: The type of the connector (e.g., 'postgres').
            connection_params: The parameters needed to initialize the connection.

        Returns:
            An instance of the requested connector, or raises ValueError / ImportError if not found.
        """
        connector_class = self.connectors.get(connector_type)
        if not connector_class:
            if connector_type in self._missing_connectors:
                err_detail = self._missing_connectors[connector_type]
                extra_name = CONNECTOR_EXTRA_MAP.get(connector_type, connector_type)
                logger.error(
                    f"Connector '{connector_type}' unavailable due to missing dependencies: {err_detail}"
                )
                raise ImportError(
                    f"Connector type '{connector_type}' is unavailable because its dependencies are not installed. "
                    f"Install it with: pip install 'irides-core[{extra_name}]' (Error: {err_detail})"
                )
            logger.error(f"Connector type '{connector_type}' not found.")
            raise ValueError(
                f"Connector type '{connector_type}' not found. Available: {self.get_available_connectors()}"
            )

        return connector_class(
            connection_params=connection_params, cache_manager=self.cache_manager
        )



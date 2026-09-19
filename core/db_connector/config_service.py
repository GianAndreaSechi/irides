from typing import Dict, Any, List, Optional
from loguru import logger

from core.db_connector.manager import ConnectorManager
from core.db_connector.models import Instance
from core.db_connector.configurations import get_db_configurations


class ConfigService:
    def __init__(self, connector_manager: ConnectorManager, config_file: Optional[str] = None):
        self.connector_manager = connector_manager
        self.db_configurations: Dict[str, Dict[str, Any]] = get_db_configurations(config_file=config_file)
        logger.info(f"ConfigService: Initialized with {len(self.db_configurations)} database configurations.")

    def get_available_configurations(self) -> List[str]:
        logger.info("ConfigService: Fetching available configurations.")
        return list(self.db_configurations.keys())

    def _get_connector_details(self, config_name: str) -> Dict[str, Any]:
        config = self.db_configurations.get(config_name)
        if not config:
            logger.error(f"ConfigService: Configuration name '{config_name}' not found.")
            raise ValueError(f"Configuration name '{config_name}' not found.")

        connector_type = config.get("connector_type")
        connection_params = config.get("connection_params")

        if not connector_type or not connection_params:
            raise ValueError(
                f"ConfigService: Configuration '{config_name}' is missing "
                "'connector_type' or 'connection_params'."
            )
        return {"connector_type": connector_type, "connection_params": connection_params}

    def _get_hosts(self, config_name: str) -> List[str]:
        """Return explicitly configured connection hosts, when present.

        Configurations may use either a multi-host ``hosts`` collection or a
        flat ``host`` connection parameter. Connectors such as Athena and
        DynamoDB discover instances remotely and expose neither.
        """
        details = self._get_connector_details(config_name)
        connection_params = details["connection_params"]
        hosts = [item["host"] for item in connection_params.get("hosts", [])]
        if hosts:
            return hosts
        return [connection_params["host"]] if connection_params.get("host") else []

    def configuration_matches_instance(
        self, config_name: str, instance_name: str, no_cache: bool = False
    ) -> bool:
        """Return whether an instance belongs to a database configuration."""
        configured_hosts = self._get_hosts(config_name)
        if configured_hosts:
            return instance_name in configured_hosts
        return instance_name in {
            instance.name for instance in self.list_instances(config_name, no_cache=no_cache)
        }

    def resolve_configurations_for_instance(
        self, instance_name: str, no_cache: bool = False
    ) -> List[str]:
        return [
            config_name
            for config_name in self.get_available_configurations()
            if self.configuration_matches_instance(config_name, instance_name, no_cache)
        ]

    def _get_connector_for_host(self, config_name: str, host: str):
        details = self._get_connector_details(config_name)
        host_params = next(
            (h for h in details["connection_params"].get("hosts", []) if h["host"] == host),
            None,
        )
        if host_params:
            return self.connector_manager.get_connector(details["connector_type"], host_params)

        # Flat connection parameters identify one connection, while ``host`` is
        # an instance/catalog/region discovered through that connection.
        if not details["connection_params"].get("hosts"):
            return self.connector_manager.get_connector(
                details["connector_type"], details["connection_params"]
            )
        raise ValueError(f"Host '{host}' not found in config '{config_name}'")

    def list_instances(self, config_name: str, no_cache: bool = False) -> List[Instance]:
        """List instances for both multi-host and flat connector configurations."""
        configured_hosts = self._get_hosts(config_name)
        if configured_hosts:
            instances: List[Instance] = []
            for host in configured_hosts:
                connector = self._get_connector_for_host(config_name, host)
                instances.extend(connector.list_instances(no_cache=no_cache))
            return instances

        details = self._get_connector_details(config_name)
        connector = self.connector_manager.get_connector(
            details["connector_type"], details["connection_params"]
        )
        return connector.list_instances(no_cache=no_cache)

    def resolve_instance_names(
        self, config_name: str, instance_name: Optional[str] = None, no_cache: bool = False
    ) -> List[str]:
        if instance_name:
            return [instance_name]
        return [instance.name for instance in self.list_instances(config_name, no_cache)]

    def test_connection(self, config_name: str):
        logger.info(f"ConfigService: Attempting to test connection for config: {config_name}")
        for instance in self.list_instances(config_name, no_cache=True):
            logger.info(
                f"ConfigService: Successfully tested connection to {instance.name} "
                f"for config: {config_name}"
            )
        return {"message": f"Successfully connected to all hosts in {config_name}."}

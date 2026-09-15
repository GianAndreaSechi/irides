from typing import List, Optional
from loguru import logger

from core.db_connector.manager import ConnectorManager
from core.db_connector.models import Schema
from core.db_connector.config_service import ConfigService

class SchemaService:
    def __init__(self, config_service: ConfigService, connector_manager: ConnectorManager):
        self.config_service = config_service
        self.connector_manager = connector_manager

    def list_schemas(self, config_name: Optional[str] = None, instance_name: Optional[str] = None, no_cache: bool = False) -> List[Schema]:
        all_schemas = []
        config_names_to_process = [config_name] if config_name else self.config_service.get_available_configurations()

        for c_name in config_names_to_process:
            hosts_to_process = self.config_service.resolve_instance_names(c_name, instance_name, no_cache)

            for host in hosts_to_process:
                logger.info(f"SchemaService: Listing schemas for config: {c_name}, host: {host}")
                connector = self.config_service._get_connector_for_host(c_name, host)
                schemas = connector.list_schemas(instance_name=host, no_cache=no_cache)
                all_schemas.extend(schemas)
                logger.info(f"SchemaService: Found {len(schemas)} schemas for host: {host}")
        return all_schemas
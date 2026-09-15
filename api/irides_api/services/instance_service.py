from typing import List, Optional
from loguru import logger

from core.db_connector.manager import ConnectorManager
from core.db_connector.models import Instance
from core.db_connector.config_service import ConfigService

class InstanceService:
    def __init__(self, config_service: ConfigService, connector_manager: ConnectorManager):
        self.config_service = config_service
        self.connector_manager = connector_manager

    def list_instances(self, config_names: Optional[List[str]] = None, no_cache: bool = False) -> List[Instance]:
        all_instances = []
        if not config_names:
            config_names = self.config_service.get_available_configurations()

        for c_name in config_names:
            logger.info(f"InstanceService: Listing instances for config: {c_name}")
            instances = self.config_service.list_instances(c_name, no_cache=no_cache)
            all_instances.extend(instances)
            logger.info(f"InstanceService: Found {len(instances)} instances for config: {c_name}")
        return all_instances

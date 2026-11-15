from typing import List, Optional

from core.db_connector.catalog import Catalog
from core.db_connector.config_service import ConfigService
from core.db_connector.manager import ConnectorManager
from core.db_connector.models import Instance


class InstanceService:
    def __init__(self, config_service: ConfigService, connector_manager: ConnectorManager):
        self.config_service = config_service
        self.connector_manager = connector_manager
        self.catalog = Catalog(config_service=config_service)

    def list_instances(
        self, config_names: Optional[List[str]] = None, no_cache: bool = False
    ) -> List[Instance]:
        return self.catalog.instances(target=config_names, no_cache=no_cache)

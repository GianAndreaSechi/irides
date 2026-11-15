from typing import List, Optional

from core.db_connector.catalog import Catalog
from core.db_connector.config_service import ConfigService
from core.db_connector.manager import ConnectorManager
from core.db_connector.models import Table


class TableService:
    def __init__(self, config_service: ConfigService, connector_manager: ConnectorManager):
        self.config_service = config_service
        self.connector_manager = connector_manager
        self.catalog = Catalog(config_service=config_service)

    def list_tables(
        self,
        config_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        no_cache: bool = False,
    ) -> List[Table]:
        return self.catalog.tables(
            config_name=config_name,
            instance_name=instance_name,
            schema_name=schema_name,
            limit=limit,
            offset=offset,
            no_cache=no_cache,
        )

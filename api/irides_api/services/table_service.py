from typing import List, Optional
from loguru import logger

from core.db_connector.manager import ConnectorManager
from core.db_connector.models import Schema, Table
from core.db_connector.config_service import ConfigService

class TableService:
    def __init__(self, config_service: ConfigService, connector_manager: ConnectorManager): 
        self.config_service = config_service
        self.connector_manager = connector_manager

    def list_tables(self, config_name: Optional[str] = None, instance_name: Optional[str] = None, schema_name: Optional[str] = None, limit: Optional[int] = None, offset: Optional[int] = None, no_cache: bool = False) -> List[Table]:
        all_tables = []
        config_names_to_process = [config_name] if config_name else self.config_service.get_available_configurations()

        for c_name in config_names_to_process:
            hosts_to_process = self.config_service.resolve_instance_names(c_name, instance_name, no_cache)

            for host in hosts_to_process:
                connector = self.config_service._get_connector_for_host(c_name, host)

                schemas_to_process = []
                if schema_name:
                    schemas_to_process.append(Schema(name=schema_name))
                else:
                    schemas_to_process = connector.list_schemas(instance_name=host, no_cache=no_cache)

                for sch in schemas_to_process:
                    logger.info(f"TableService: Listing tables for config: {c_name}, host: {host}, schema: {sch.name}")
                    tables = connector.list_tables(instance_name=host, schema_name=sch.name, limit=limit, offset=offset, no_cache=no_cache)
                    all_tables.extend(tables)
                    logger.info(f"TableService: Found {len(tables)} tables for schema: {sch.name}")
        return all_tables

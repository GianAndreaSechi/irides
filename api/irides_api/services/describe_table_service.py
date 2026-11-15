from typing import List, Optional

from core.db_connector.ai_service import AIDocumentationService
from core.db_connector.catalog import Catalog
from core.db_connector.config_service import ConfigService
from core.db_connector.exporting import ExportOptions
from core.db_connector.manager import ConnectorManager
from core.db_connector.models import TableDescription
from core.db_connector.storage import get_metadata_store


class DescribeTableService:
    def __init__(self, config_service: ConfigService, connector_manager: ConnectorManager):
        self.config_service = config_service
        self.connector_manager = connector_manager
        self.catalog = Catalog(config_service=config_service)

    def describe_table(
        self,
        config_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        no_cache: bool = False,
        generate_ai_docs: bool = False,
        save_metadata: bool = True,
        only_if_changed: bool = False,
        export_options: Optional[ExportOptions] = None,
    ) -> List[TableDescription]:
        options = export_options or ExportOptions()
        metadata_store = get_metadata_store() if (save_metadata or options.formats) else None
        ai_service = AIDocumentationService() if generate_ai_docs else None
        outcomes = self.catalog.describe(
            config_name=config_name,
            instance_name=instance_name,
            schema_name=schema_name,
            table_name=table_name,
            no_cache=no_cache,
            generate_ai_docs=generate_ai_docs,
            save_metadata=save_metadata,
            only_if_changed=only_if_changed,
            export_options=options,
            fail_fast=True,
            ai_service=ai_service,
            metadata_store=metadata_store,
        )
        return [item.description for item in outcomes if item.description is not None]

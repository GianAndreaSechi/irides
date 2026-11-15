"""Operations over metadata persisted by core."""

from typing import Any, Dict, Optional

from core.db_connector.exporting import ExportOptions
from core.db_connector.storage import BaseMetadataStore, get_metadata_store

from irides_cli.dto.requests import MetadataUpdateRequest, PageRequest


class MetadataService:
    def __init__(self, store: Optional[BaseMetadataStore] = None) -> None:
        self.store = store or get_metadata_store()

    def instances(self, page: PageRequest, config_name: Optional[str] = None) -> Dict[str, Any]:
        if page.page < 1 or page.page_size < 1:
            raise ValueError("page and page_size must be positive integers.")
        return self.store.list_instances(page.page, page.page_size, config_name=config_name)

    def databases(
        self, instance_name: str, page: PageRequest, config_name: Optional[str] = None
    ) -> Dict[str, Any]:
        if page.page < 1 or page.page_size < 1:
            raise ValueError("page and page_size must be positive integers.")
        return self.store.list_databases(
            instance_name, page.page, page.page_size, config_name=config_name
        )

    def tables(
        self,
        instance_name: str,
        database_name: str,
        page: PageRequest,
        config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if page.page < 1 or page.page_size < 1:
            raise ValueError("page and page_size must be positive integers.")
        return self.store.list_tables_metadata(
            instance_name, database_name, page.page, page.page_size, config_name=config_name
        )

    def get(
        self,
        instance_name: str,
        database_name: str,
        table_name: str,
        config_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.store.find_table_metadata(
            instance_name,
            database_name,
            table_name,
            config_name=config_name,
            strict=(config_name is None),
        )

    def update(self, request: MetadataUpdateRequest) -> Optional[Dict[str, Any]]:
        return self.store.update_table_metadata(
            request.instance_name,
            request.database_name,
            request.table_name,
            request.payload,
            config_name=request.config_name,
            strict=(request.config_name is None),
        )

    def export_all(
        self,
        options: Optional[ExportOptions] = None,
        config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if hasattr(self.store, "export_all"):
            count = self.store.export_all(export_options=options, config_name=config_name)
        else:
            count = 0
        return {"exported_count": count, "config_name": config_name}

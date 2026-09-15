"""Operations over metadata persisted by core."""

from typing import Any, Dict, Optional

from core.db_connector.storage import BaseMetadataStore, get_metadata_store

from irides_cli.dto.requests import MetadataUpdateRequest, PageRequest


class MetadataService:
    def __init__(self, store: Optional[BaseMetadataStore] = None) -> None:
        self.store = store or get_metadata_store()

    def instances(self, page: PageRequest) -> Dict[str, Any]:
        return self.store.list_instances(page.page, page.page_size)

    def databases(self, instance_name: str, page: PageRequest) -> Dict[str, Any]:
        return self.store.list_databases(instance_name, page.page, page.page_size)

    def tables(self, instance_name: str, database_name: str, page: PageRequest) -> Dict[str, Any]:
        return self.store.list_tables_metadata(instance_name, database_name, page.page, page.page_size)

    def get(self, instance_name: str, database_name: str, table_name: str) -> Optional[Dict[str, Any]]:
        return self.store.find_table_metadata(instance_name, database_name, table_name)

    def update(self, request: MetadataUpdateRequest) -> Optional[Dict[str, Any]]:
        return self.store.update_table_metadata(request.instance_name, request.database_name, request.table_name, request.payload)

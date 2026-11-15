from typing import Any, Dict, List, Optional

from core.db_connector.storage import BaseMetadataStore


class MetadataService:
    def __init__(self, metadata_store: BaseMetadataStore):
        self.store = metadata_store

    def list_configs(self) -> List[str]:
        if hasattr(self.store, "list_configs"):
            return self.store.list_configs()
        return []

    def list_instances(
        self, page: int, page_size: int, config_name: Optional[str] = None
    ) -> Dict[str, Any]:
        return self.store.list_instances(page=page, page_size=page_size, config_name=config_name)

    def list_databases(
        self, instance: str, page: int, page_size: int, config_name: Optional[str] = None
    ) -> Dict[str, Any]:
        return self.store.list_databases(
            instance_name=instance, page=page, page_size=page_size, config_name=config_name
        )

    def list_tables(
        self,
        instance: str,
        database: str,
        page: int,
        page_size: int,
        config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.store.list_tables_metadata(
            instance_name=instance,
            database_name=database,
            page=page,
            page_size=page_size,
            config_name=config_name,
        )

    def get_table(
        self, instance: str, database: str, table: str, config_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        return self.store.find_table_metadata(
            instance_name=instance,
            database_name=database,
            table_name=table,
            config_name=config_name,
            strict=(config_name is None),
        )

    def update_table(
        self,
        instance: str,
        database: str,
        table: str,
        payload: Dict[str, Any],
        config_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.store.update_table_metadata(
            instance_name=instance,
            database_name=database,
            table_name=table,
            payload=payload,
            config_name=config_name,
            strict=(config_name is None),
        )

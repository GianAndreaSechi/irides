"""Core-backed synchronous database introspection use cases."""

import os
from typing import Any, Dict, List

from core.db_connector.cache_manager import CacheManager, NullCacheManager
from core.db_connector.catalog import Catalog
from core.db_connector.config_service import ConfigService
from core.db_connector.exporting import ExportFormat, ExportOptions
from core.db_connector.manager import ConnectorManager

from irides_cli.dto.requests import DescribeRequest, ScopeRequest, TablesRequest


class IntrospectionService:
    """Runs live introspection by delegating domain orchestration to core.Catalog."""

    def __init__(
        self,
        config_service: ConfigService | None = None,
        config_file: str | None = None,
        no_cache: bool = False,
    ) -> None:
        if config_service is None:
            if no_cache:
                cache: CacheManager = NullCacheManager()
            else:
                cache = CacheManager(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=int(os.getenv("REDIS_DB", "0")),
                    ttl_seconds=int(os.getenv("REDIS_TTL_SECONDS", "86400")),
                    socket_connect_timeout=float(
                        os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", "2")
                    ),
                    socket_timeout=float(os.getenv("REDIS_CACHE_SOCKET_TIMEOUT_SECONDS", "2")),
                )
            config_service = ConfigService(ConnectorManager(cache), config_file=config_file)
        self.config_service = config_service
        self.catalog = Catalog(config_service=config_service)

    def configurations(self) -> List[str]:
        return self.catalog.configurations()

    def connect(self, config_name: str) -> Dict[str, Any]:
        return self.catalog.connect(config_name)

    def instances(self, request: ScopeRequest) -> List[Any]:
        return self.catalog.instances(
            config_name=request.config_name, no_cache=request.no_cache
        )

    def schemas(self, request: ScopeRequest) -> List[Any]:
        return self.catalog.schemas(
            config_name=request.config_name,
            instance_name=request.instance_name,
            no_cache=request.no_cache,
        )

    def tables(self, request: TablesRequest) -> List[Any]:
        return self.catalog.tables(
            config_name=request.config_name,
            instance_name=request.instance_name,
            schema_name=request.schema_name,
            limit=request.limit,
            offset=request.offset,
            no_cache=request.no_cache,
        )

    def describe(self, request: DescribeRequest) -> List[Any]:
        formats = []
        if request.export_markdown:
            formats.append(ExportFormat.MARKDOWN)
        if request.export_okf:
            formats.append(ExportFormat.OKF)
        export_options = ExportOptions(formats=formats, preformat=request.preformat)
        outcomes = self.catalog.describe(
            config_name=request.config_name,
            instance_name=request.instance_name,
            schema_name=request.schema_name,
            table_name=request.table_name,
            no_cache=request.no_cache,
            generate_ai_docs=request.generate_ai_docs,
            save_metadata=request.save_metadata,
            only_if_changed=request.only_if_changed,
            export_options=export_options,
            fail_fast=True,
        )
        return [item.description for item in outcomes if item.description is not None]

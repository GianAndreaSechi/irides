"""Core-backed synchronous database introspection use cases."""

import os
from typing import Any, Dict, Iterable, List

from core.db_connector.ai_service import AIDocumentationService
from core.db_connector.cache_manager import CacheManager
from core.db_connector.config_service import ConfigService
from core.db_connector.manager import ConnectorManager
from core.db_connector.models import Schema, Table
from core.db_connector.storage import get_metadata_store
from core.db_connector.exporting import ExportFormat, ExportOptions

from irides_cli.dto.requests import DescribeRequest, ScopeRequest, TablesRequest


class IntrospectionService:
    """Runs live introspection without any dependency on API-layer code."""

    def __init__(self, config_service: ConfigService | None = None) -> None:
        if config_service is None:
            cache = CacheManager(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                ttl_seconds=int(os.getenv("REDIS_TTL_SECONDS", "86400")),
                socket_connect_timeout=float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", "2")),
                socket_timeout=float(os.getenv("REDIS_CACHE_SOCKET_TIMEOUT_SECONDS", "2")),
            )
            config_service = ConfigService(ConnectorManager(cache))
        self.config_service = config_service

    def configurations(self) -> List[str]:
        return self.config_service.get_available_configurations()

    def connect(self, config_name: str) -> Dict[str, Any]:
        return self.config_service.test_connection(config_name)

    def instances(self, request: ScopeRequest) -> List[Any]:
        names = [request.config_name] if request.config_name else self.configurations()
        return [instance for name in names for instance in self.config_service.list_instances(name, no_cache=request.no_cache)]

    def _scope(self, request: ScopeRequest) -> Iterable[tuple[str, str, Any]]:
        configs = [request.config_name] if request.config_name else self.configurations()
        for config in configs:
            for instance in self.config_service.resolve_instance_names(config, request.instance_name, request.no_cache):
                yield config, instance, self.config_service._get_connector_for_host(config, instance)

    def schemas(self, request: ScopeRequest) -> List[Any]:
        return [schema for _, instance, connector in self._scope(request) for schema in connector.list_schemas(instance_name=instance, no_cache=request.no_cache)]

    def tables(self, request: TablesRequest) -> List[Any]:
        found = []
        for _, instance, connector in self._scope(request):
            schemas = [Schema(name=request.schema_name)] if request.schema_name else connector.list_schemas(instance_name=instance, no_cache=request.no_cache)
            for schema in schemas:
                found.extend(connector.list_tables(instance_name=instance, schema_name=schema.name, limit=request.limit, offset=request.offset, no_cache=request.no_cache))
        return found

    def describe(self, request: DescribeRequest) -> List[Any]:
        results = []
        formats = []
        if request.export_markdown:
            formats.append(ExportFormat.MARKDOWN)
        if request.export_okf:
            formats.append(ExportFormat.OKF)
        export_options = ExportOptions(formats=formats, preformat=request.preformat)
        store = get_metadata_store() if request.save_metadata or formats else None
        ai_service = AIDocumentationService() if request.generate_ai_docs else None
        for config, instance, connector in self._scope(request):
            schemas = [Schema(name=request.schema_name)] if request.schema_name else connector.list_schemas(instance_name=instance, no_cache=request.no_cache)
            for schema in schemas:
                tables = [Table(name=request.table_name, schema_name=schema.name)] if request.table_name else connector.list_tables(instance_name=instance, schema_name=schema.name, no_cache=request.no_cache)
                for table in tables:
                    description = connector.describe_table(instance_name=instance, schema_name=schema.name, table_name=table.name, no_cache=request.no_cache)
                    schema_description = description.model_dump(exclude={"ai_documentation", "ai_generation_status", "ai_generation_error"})
                    ai_documentation = None
                    if ai_service:
                        ai_documentation = ai_service.generate_table_documentation(schema_description)
                        description = description.model_copy(update={"ai_documentation": ai_documentation, "ai_generation_status": "generated" if ai_documentation else "failed", "ai_generation_error": None if ai_documentation else ai_service.last_error})
                    results.append(description)
                    if store:
                        store.save_table_metadata(
                            config,
                            instance,
                            schema.name,
                            table.name,
                            schema_description,
                            ai_documentation,
                            only_if_changed=request.only_if_changed,
                            export_options=export_options,
                            save_metadata=request.save_metadata,
                        )
        return results

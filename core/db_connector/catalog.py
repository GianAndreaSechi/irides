"""Public Catalog facade and shared introspection use cases for Irides Core."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from .ai_service import AIDocumentationService
from .cache_manager import CacheManager, NullCacheManager
from .config_service import ConfigService
from .exporting import ExportFormat, ExportOptions
from .manager import ConnectorManager
from .models import Instance, Schema, Table, TableDescription
from .storage import BaseMetadataStore, get_metadata_store


@dataclass(frozen=True)
class DescribeOutcome:
    """Result of describing, persisting, and exporting a single table resource."""

    config_name: str
    instance_name: str
    schema_name: str
    table_name: str
    description: Optional[TableDescription] = None
    document: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.description is not None

    @property
    def table(self) -> Optional[TableDescription]:
        return self.description


def build_schema_description(desc: TableDescription) -> Dict[str, Any]:
    """Serialize a TableDescription into the canonical schema_description dictionary."""
    return desc.model_dump(
        exclude={
            "config_name",
            "ai_documentation",
            "ai_generation_status",
            "ai_generation_error",
        }
    )



class Catalog:
    """High-level public entrypoint for inspecting databases and exporting catalogs."""

    def __init__(
        self,
        config_service: Optional[ConfigService] = None,
        metadata_store: Optional[BaseMetadataStore] = None,
        *,
        config_file: Optional[str] = None,
        cache: Optional[CacheManager] = None,
    ):
        if config_service is None:
            cache_mgr = cache if cache is not None else NullCacheManager()
            manager = ConnectorManager(cache_mgr)
            config_service = ConfigService(manager, config_file=config_file)
        self.config_service = config_service
        self.metadata_store = metadata_store

    @classmethod
    def from_config(
        cls,
        config_file: Optional[str] = None,
        *,
        cache: Optional[CacheManager] = None,
        metadata_store: Optional[BaseMetadataStore] = None,
    ) -> "Catalog":
        cache_mgr = cache if cache is not None else NullCacheManager()
        manager = ConnectorManager(cache_mgr)
        config_service = ConfigService(manager, config_file=config_file)
        return cls(config_service=config_service, metadata_store=metadata_store)

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close underlying cache connections if active."""
        cache = getattr(self.config_service.connector_manager, "cache_manager", None)
        client = getattr(cache, "redis_client", None)
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass

    def configurations(self) -> List[str]:
        return self.config_service.get_available_configurations()

    def connect(self, target: str) -> Dict[str, Any]:
        return self.config_service.test_connection(target)

    def resolve_scope(
        self,
        target: Optional[str] = None,
        instance: Optional[str] = None,
        *,
        no_cache: bool = False,
    ) -> Iterable[tuple[str, str, Any]]:
        if target:
            configs = [target]
        elif instance:
            configs = [
                c
                for c in self.configurations()
                if self.config_service.configuration_matches_instance(c, instance, no_cache)
            ]
        else:
            configs = self.configurations()

        for cfg in configs:
            for inst in self.config_service.resolve_instance_names(cfg, instance, no_cache):
                connector = self.config_service._get_connector_for_host(cfg, inst)
                yield cfg, inst, connector

    def instances(
        self,
        target: Optional[str] = None,
        *,
        config_name: Optional[str] = None,
        no_cache: bool = False,
    ) -> List[Instance]:
        effective_target = target or config_name
        names = [effective_target] if effective_target else self.configurations()
        return [
            inst
            for name in names
            for inst in self.config_service.list_instances(name, no_cache=no_cache)
        ]

    def schemas(
        self,
        target: Optional[str] = None,
        instance: Optional[str] = None,
        *,
        config_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        no_cache: bool = False,
    ) -> List[Schema]:
        effective_target = target or config_name
        effective_instance = instance or instance_name
        found: List[Schema] = []
        for _, inst, connector in self.resolve_scope(
            effective_target, effective_instance, no_cache=no_cache
        ):
            found.extend(connector.list_schemas(instance_name=inst, no_cache=no_cache))
        return found

    def tables(
        self,
        target: Optional[str] = None,
        instance: Optional[str] = None,
        schema: Optional[str] = None,
        *,
        config_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        no_cache: bool = False,
    ) -> List[Table]:
        effective_target = target or config_name
        effective_instance = instance or instance_name
        effective_schema = schema or schema_name
        found: List[Table] = []
        for _, inst, connector in self.resolve_scope(
            effective_target, effective_instance, no_cache=no_cache
        ):
            schemas = (
                [Schema(name=effective_schema)]
                if effective_schema
                else connector.list_schemas(instance_name=inst, no_cache=no_cache)
            )
            for sch in schemas:
                found.extend(
                    connector.list_tables(
                        instance_name=inst,
                        schema_name=sch.name,
                        limit=limit,
                        offset=offset,
                        no_cache=no_cache,
                    )
                )
        return found

    def describe(
        self,
        target: Optional[str] = None,
        instance: Optional[str] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        *,
        config_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        no_cache: bool = False,
        generate_ai_docs: bool = False,
        save_metadata: bool = False,
        only_if_changed: bool = False,
        export_options: Optional[ExportOptions] = None,
    ) -> List[DescribeOutcome]:
        effective_target = target or config_name
        effective_instance = instance or instance_name
        effective_schema = schema or schema_name
        effective_table = table or table_name
        options = export_options or ExportOptions(formats=[])
        store = self.metadata_store
        if store is None and (save_metadata or options.formats):
            store = get_metadata_store()
        ai_service = AIDocumentationService() if generate_ai_docs else None
        outcomes: List[DescribeOutcome] = []

        for cfg, inst, connector in self.resolve_scope(
            effective_target, effective_instance, no_cache=no_cache
        ):
            schemas = (
                [Schema(name=effective_schema)]
                if effective_schema
                else connector.list_schemas(instance_name=inst, no_cache=no_cache)
            )
            for sch in schemas:
                tables = (
                    [Table(name=effective_table, schema_name=sch.name)]
                    if effective_table
                    else connector.list_tables(
                        instance_name=inst, schema_name=sch.name, no_cache=no_cache
                    )
                )
                for tbl in tables:
                    try:
                        desc = connector.describe_table(
                            instance_name=inst,
                            schema_name=sch.name,
                            table_name=tbl.name,
                            no_cache=no_cache,
                        ).model_copy(update={"config_name": cfg})
                        schema_dict = build_schema_description(desc)
                        ai_doc = None
                        if ai_service:
                            existing = (
                                store.get_table_metadata(cfg, inst, sch.name, tbl.name)
                                if (store and only_if_changed)
                                else None
                            )
                            if (
                                existing
                                and existing.get("schema_description") == schema_dict
                                and existing.get("ai_documentation")
                            ):
                                ai_doc = existing["ai_documentation"]
                                desc = desc.model_copy(
                                    update={
                                        "ai_documentation": ai_doc,
                                        "ai_generation_status": "reused",
                                        "ai_generation_error": None,
                                    }
                                )
                            else:
                                outcome = ai_service.generate_with_outcome(schema_dict)
                                ai_doc = outcome.documentation
                                desc = desc.model_copy(
                                    update={
                                        "ai_documentation": ai_doc,
                                        "ai_generation_status": outcome.status,
                                        "ai_generation_error": outcome.error,
                                    }
                                )
                        doc_record = None
                        if store and (save_metadata or options.formats):
                            doc_record = store.save_table_metadata(
                                config_name=cfg,
                                instance_name=inst,
                                schema_name=sch.name,
                                table_name=tbl.name,
                                schema_description=schema_dict,
                                ai_documentation=ai_doc,
                                only_if_changed=only_if_changed,
                                export_options=options,
                                save_metadata=save_metadata,
                            )
                        outcomes.append(
                            DescribeOutcome(
                                config_name=cfg,
                                instance_name=inst,
                                schema_name=sch.name,
                                table_name=tbl.name,
                                description=desc,
                                document=doc_record,
                            )
                        )
                    except Exception as exc:
                        outcomes.append(
                            DescribeOutcome(
                                config_name=cfg,
                                instance_name=inst,
                                schema_name=sch.name,
                                table_name=tbl.name,
                                error=str(exc),
                            )
                        )
        return outcomes

    def export(
        self,
        document: Dict[str, Any],
        formats: Sequence[str | ExportFormat] = ("markdown", "okf"),
        *,
        preformat: bool = True,
    ) -> None:
        store = self.metadata_store or get_metadata_store()
        parsed_formats = [
            f if isinstance(f, ExportFormat) else ExportFormat(f) for f in formats
        ]
        options = ExportOptions(formats=parsed_formats, preformat=preformat)
        if hasattr(store, "artifact_store"):
            store.artifact_store.export(document, options)

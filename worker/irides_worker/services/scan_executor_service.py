from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from core.db_connector.config_service import ConfigService
from core.db_connector.job_store import JobStore
from core.db_connector.models import Schema
from core.db_connector.ai_service import AIDocumentationService
from core.db_connector.storage import get_metadata_store
from core.db_connector.exporting import ExportOptions


@dataclass
class ScanExecutionResult:
    count: int = 0
    errors: list[str] = field(default_factory=list)


class ScanExecutorService:
    def __init__(self, job_store: JobStore, config_service: ConfigService):
        self.job_store = job_store
        self.config_service = config_service

    def execute(
        self,
        job_id: str,
        config_name: Optional[str],
        instance_name: Optional[str],
        schema_name: Optional[str],
        no_cache: bool = False,
        generate_ai_docs: bool = False,
        save_metadata: bool = True,
        only_if_changed: bool = False,
        export_options: Optional[ExportOptions] = None,
    ) -> ScanExecutionResult:
        """
        Scans tables according to the given scope, stores each TableDescription
        in Redis, optionally generates AI documentation, persists metadata to disk/store,
        and returns the total count of described tables.
        """
        result = ScanExecutionResult()
        config_names = (
            [config_name] if config_name
            else self.config_service.get_available_configurations()
        )

        # Keep only configurations that own the requested instance. The API
        # normally resolves a unique configuration before enqueueing, while this
        # remains a defensive check for legacy or externally-produced messages.
        if instance_name and not config_name:
            config_names = [
                candidate
                for candidate in config_names
                if self.config_service.configuration_matches_instance(
                    candidate, instance_name, no_cache
                )
            ]

        export_options = export_options or ExportOptions()
        metadata_store = get_metadata_store() if save_metadata or export_options.formats else None
        ai_service = AIDocumentationService() if generate_ai_docs else None
        logger.info(
            "ScanExecutorService [{}]: AI documentation generation is {}.",
            job_id,
            "enabled" if generate_ai_docs else "disabled",
        )

        for c_name in config_names:
            try:
                hosts = self.config_service.resolve_instance_names(c_name, instance_name, no_cache)

                for host in hosts:
                    connector = self.config_service._get_connector_for_host(c_name, host)

                    schemas = (
                        [Schema(name=schema_name)]
                        if schema_name
                        else connector.list_schemas(instance_name=host, no_cache=no_cache)
                    )

                    for sch in schemas:
                        tables = connector.list_tables(
                            instance_name=host,
                            schema_name=sch.name,
                            no_cache=no_cache
                        )

                        for tbl in tables:
                            logger.info(
                                f"ScanExecutorService [{job_id}]: "
                                f"{c_name}/{host}/{sch.name}/{tbl.name} (no_cache={no_cache})"
                            )
                            try:
                                desc = connector.describe_table(
                                    instance_name=host,
                                    schema_name=sch.name,
                                    table_name=tbl.name,
                                    no_cache=no_cache,
                                )
                                desc_dict = desc.model_dump(
                                    exclude={"ai_documentation", "ai_generation_status", "ai_generation_error"}
                                )
                                ai_doc = None
                                ai_status = None
                                ai_error = None
                                if ai_service:
                                    logger.info(
                                        "ScanExecutorService [{}]: Generating AI documentation for {}/{}/{}.",
                                        job_id,
                                        c_name,
                                        sch.name,
                                        tbl.name,
                                    )
                                    ai_doc = ai_service.generate_table_documentation(desc_dict)
                                    ai_status = "generated" if ai_doc else "failed"
                                    ai_error = None if ai_doc else ai_service.last_error

                                result_dict = dict(desc_dict)
                                if ai_service:
                                    result_dict["ai_documentation"] = ai_doc
                                    result_dict["ai_generation_status"] = ai_status
                                    result_dict["ai_generation_error"] = ai_error

                                self.job_store.append_result(job_id, result_dict)

                                if metadata_store:
                                    metadata_store.save_table_metadata(
                                        config_name=c_name,
                                        instance_name=host,
                                        schema_name=sch.name,
                                        table_name=tbl.name,
                                        schema_description=desc_dict,
                                        ai_documentation=ai_doc,
                                        only_if_changed=only_if_changed,
                                        export_options=export_options,
                                        save_metadata=save_metadata,
                                    )

                                result.count += 1
                            except Exception as e:
                                error = f"{c_name}/{host}/{sch.name}/{tbl.name}: {e}"
                                result.errors.append(error)
                                logger.warning(
                                    f"ScanExecutorService [{job_id}]: failed to describe "
                                    f"{sch.name}.{tbl.name}: {e}"
                                )
            except Exception as e:
                error = f"{c_name}: {e}"
                result.errors.append(error)
                logger.warning(
                    f"ScanExecutorService [{job_id}]: error processing config {c_name}: {e}"
                )

        return result

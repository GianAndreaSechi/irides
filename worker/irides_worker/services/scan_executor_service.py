from dataclasses import dataclass, field
import os
import time
from typing import Optional
from loguru import logger

from core.db_connector.ai_service import AIDocumentationService
from core.db_connector.catalog import Catalog, build_schema_description
from core.db_connector.config_service import ConfigService
from core.db_connector.exporting import ExportOptions
from core.db_connector.job_store import JobStore
from core.db_connector.storage import get_metadata_store


@dataclass
class ScanExecutionResult:
    count: int = 0
    errors: list[str] = field(default_factory=list)


class ScanExecutorService:
    def __init__(self, job_store: JobStore, config_service: ConfigService):
        self.job_store = job_store
        self.config_service = config_service
        self.catalog = Catalog(config_service=config_service)

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
        consumer_name: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> ScanExecutionResult:
        """
        Streams table introspection via core.Catalog, persists results to Redis JobStore,
        sends periodic heartbeats, and collects per-table/per-config errors.
        """
        result = ScanExecutionResult()
        options = export_options if export_options is not None else ExportOptions()
        metadata_store = get_metadata_store() if (save_metadata or options.formats) else None
        ai_service = AIDocumentationService() if generate_ai_docs else None
        heartbeat_interval = float(os.getenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "30"))
        last_heartbeat = 0.0
        logger.info(
            "ScanExecutorService [{}]: AI documentation generation is {}.",
            job_id,
            "enabled" if generate_ai_docs else "disabled",
        )

        for outcome in self.catalog.iter_describe(
            config_name=config_name,
            instance_name=instance_name,
            schema_name=schema_name,
            no_cache=no_cache,
            generate_ai_docs=generate_ai_docs,
            save_metadata=save_metadata,
            only_if_changed=only_if_changed,
            export_options=options,
            fail_fast=False,
            ai_service=ai_service,
            metadata_store=metadata_store,
        ):
            if outcome.error is not None:
                result.errors.append(outcome.error)
                continue

            assert outcome.description is not None
            desc_dict = build_schema_description(outcome.description)
            result_dict = {"config_name": outcome.config_name, **desc_dict}
            if ai_service:
                result_dict["ai_documentation"] = outcome.description.ai_documentation
                result_dict["ai_generation_status"] = outcome.description.ai_generation_status
                result_dict["ai_generation_error"] = outcome.description.ai_generation_error

            self.job_store.append_result(job_id, result_dict)
            if hasattr(self.job_store, "heartbeat"):
                now_mono = time.monotonic()
                if last_heartbeat == 0.0 or (now_mono - last_heartbeat) >= heartbeat_interval:
                    self.job_store.heartbeat(
                        job_id,
                        consumer_name=consumer_name,
                        message_id=message_id,
                    )
                    last_heartbeat = now_mono

            result.count += 1

        return result

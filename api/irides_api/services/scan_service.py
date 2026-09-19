from typing import Optional, List, Dict, Any

from core.db_connector.models.scan_job import ScanJob, ScanScope
from core.db_connector.job_store import JobStore
from core.db_connector.exporting import ExportOptions
from core.db_connector.config_service import ConfigService


class ScanService:
    def __init__(self, job_store: JobStore, config_service: ConfigService):
        self.job_store = job_store
        self.config_service = config_service

    def enqueue_scan(
        self,
        config_name: Optional[str],
        instance_name: Optional[str],
        schema_name: Optional[str],
        no_cache: bool = False,
        generate_ai_docs: bool = False,
        save_metadata: bool = True,
        only_if_changed: bool = False,
        export_options: Optional[ExportOptions] = None,
    ) -> ScanJob:
        if config_name is None and instance_name:
            matching_configs = self.config_service.resolve_configurations_for_instance(
                instance_name, no_cache
            )
            if not matching_configs:
                raise ValueError(
                    f"Instance '{instance_name}' does not belong to any configured target."
                )
            if len(matching_configs) == 1:
                config_name = matching_configs[0]

        scope = ScanScope(
            config_name=config_name,
            instance_name=instance_name,
            schema_name=schema_name,
            no_cache=no_cache,
            generate_ai_docs=generate_ai_docs,
            save_metadata=save_metadata,
            only_if_changed=only_if_changed,
            export_options=export_options or ExportOptions(),
        )
        return self.job_store.enqueue(scope)


    def get_job(self, job_id: str) -> Optional[ScanJob]:
        return self.job_store.get_job(job_id)

    def get_job_results(self, job_id: str) -> List[Dict[str, Any]]:
        return self.job_store.get_results(job_id)

    def list_jobs(self, limit: int = 50) -> List[ScanJob]:
        return self.job_store.list_jobs(limit)

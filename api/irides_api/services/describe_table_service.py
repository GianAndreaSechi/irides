from typing import List, Optional
from loguru import logger

from core.db_connector.manager import ConnectorManager
from core.db_connector.config_service import ConfigService
from core.db_connector.models import Schema, Table, TableDescription
from core.db_connector.ai_service import AIDocumentationService
from core.db_connector.storage import get_metadata_store
from core.db_connector.exporting import ExportOptions

class DescribeTableService:
    def __init__(self, config_service: ConfigService, connector_manager: ConnectorManager):
        self.config_service = config_service
        self.connector_manager = connector_manager

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
        all_table_descriptions = []
        config_names_to_process = [config_name] if config_name else self.config_service.get_available_configurations()

        export_options = export_options or ExportOptions()
        metadata_store = get_metadata_store() if save_metadata or export_options.formats else None
        ai_service = AIDocumentationService() if generate_ai_docs else None
        logger.info(
            "DescribeTableService: AI documentation generation is {}.",
            "enabled" if generate_ai_docs else "disabled",
        )

        for c_name in config_names_to_process:
            hosts_to_process = self.config_service.resolve_instance_names(c_name, instance_name, no_cache)

            for host in hosts_to_process:
                connector = self.config_service._get_connector_for_host(c_name, host)

                schemas_to_process = []
                if schema_name:
                    schemas_to_process.append(Schema(name=schema_name))
                else:
                    schemas_to_process = connector.list_schemas(instance_name=host, no_cache=no_cache)

                for sch in schemas_to_process:
                    tables_to_process = []
                    if table_name:
                        tables_to_process.append(Table(name=table_name, schema_name=sch.name))
                    else:
                        tables_to_process = connector.list_tables(instance_name=host, schema_name=sch.name, no_cache=no_cache)

                    for tbl in tables_to_process:
                        logger.info(f"DescribeTableService: Describing table: {tbl.name} in schema: {sch.name}, host: {host}, config: {c_name}")
                        table_description = connector.describe_table(
                            instance_name=host,
                            schema_name=sch.name,
                            table_name=tbl.name,
                            no_cache=no_cache
                        )
                        desc_dict = table_description.model_dump(
                            exclude={"ai_documentation", "ai_generation_status", "ai_generation_error"}
                        )
                        ai_doc = None
                        ai_status = None
                        ai_error = None
                        if ai_service:
                            logger.info(
                                "DescribeTableService: Generating AI documentation for {}/{}/{}.",
                                c_name,
                                sch.name,
                                tbl.name,
                            )
                            ai_doc = ai_service.generate_table_documentation(desc_dict)
                            ai_status = "generated" if ai_doc else "failed"
                            ai_error = None if ai_doc else ai_service.last_error
                            table_description = table_description.model_copy(
                                update={
                                    "ai_documentation": ai_doc,
                                    "ai_generation_status": ai_status,
                                    "ai_generation_error": ai_error,
                                }
                            )
                        all_table_descriptions.append(table_description)

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

                        logger.info(f"DescribeTableService: Successfully described table: {tbl.name}")
        return all_table_descriptions

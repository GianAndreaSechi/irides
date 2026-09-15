from typing import Optional
from pydantic import BaseModel, Field, model_validator

from core.db_connector.exporting import ExportOptions


class DescribeTableRequest(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def migrate_save_markdown(cls, data):
        if isinstance(data, dict) and "export_options" not in data and "save_markdown" in data:
            data = dict(data)
            data["export_options"] = {
                "formats": ["markdown"] if data["save_markdown"] else [],
                "preformat": True,
            }
        return data

    config_name: Optional[str] = Field(
        default=None,
        description="Configured database target name, e.g. 'mysql_primary'.",
    )
    instance_name: Optional[str] = Field(
        default=None,
        description="Database instance returned by list_instances. For MySQL this is the configured host.",
    )
    schema_name: Optional[str] = Field(
        default=None,
        description="Schema/database name, e.g. 'quality_checks'.",
    )
    table_name: Optional[str] = Field(default=None, description="Table name to describe.")
    generate_ai_docs: bool = Field(default=False, description="Generate AI documentation.")
    save_metadata: bool = Field(default=True, description="Persist generated metadata.")
    only_if_changed: bool = Field(
        default=False,
        description="When save_metadata=True, skip writing if schema_description is unchanged. Preserves updated_at and avoids noise.",
    )
    export_options: ExportOptions = Field(
        default_factory=ExportOptions,
        description="Derived exports. Markdown, OKF and essential preformatting are enabled by default.",
    )

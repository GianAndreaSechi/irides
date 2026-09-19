from typing import Optional
from pydantic import BaseModel, Field, model_validator

from .export_options import ExportOptions


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
        description=(
            "Database instance returned by list_instances. For MySQL this is "
            "the configured MySQL host. Omit to describe tables from all instances in config_name."
        ),
    )
    schema_name: Optional[str] = Field(
        default=None,
        description="Schema/database name, e.g. 'quality_checks'.",
    )
    table_name: Optional[str] = Field(
        default=None,
        description="Table name to describe. Omit to describe all tables in the selected schema.",
    )
    generate_ai_docs: bool = Field(
        default=False,
        description=(
            "Generate AI documentation for returned table descriptions. "
            "Set true when the user asks for AI analysis, AI documentation, "
            "business documentation, or an AI-generated explanation."
        ),
    )
    save_metadata: bool = Field(
        default=True,
        description="Persist schema and AI documentation metadata when describing tables.",
    )
    only_if_changed: bool = Field(
        default=False,
        description="Skip metadata writes when the schema has not changed.",
    )
    export_options: ExportOptions = Field(
        default_factory=ExportOptions,
        description="Markdown and OKF exports with essential preformatting, enabled by default.",
    )

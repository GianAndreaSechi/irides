from typing import Optional
from pydantic import BaseModel, Field, model_validator

from .export_options import ExportOptions


class ScanRequest(BaseModel):
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

    config_name: Optional[str] = Field(default=None, description="Configured database target name.")
    instance_name: Optional[str] = Field(default=None, description="Database instance returned by list_instances.")
    schema_name: Optional[str] = Field(default=None, description="Schema/database name.")
    generate_ai_docs: bool = Field(
        default=False,
        description=(
            "Generate AI documentation for scanned tables. Set true when the user asks for AI analysis, "
            "AI documentation, business documentation, or an AI-generated explanation."
        ),
    )
    save_metadata: bool = Field(default=True, description="Persist generated metadata.")
    only_if_changed: bool = Field(default=False, description="Skip metadata writes when the schema has not changed.")
    export_options: ExportOptions = Field(
        default_factory=ExportOptions,
        description="Markdown and OKF exports with essential preformatting, enabled by default.",
    )

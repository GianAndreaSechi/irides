from typing import Optional
from pydantic import BaseModel, Field, model_validator

from core.db_connector.exporting import ExportOptions


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

    config_name: Optional[str] = None
    instance_name: Optional[str] = None
    schema_name: Optional[str] = None
    generate_ai_docs: bool = False
    save_metadata: bool = True
    only_if_changed: bool = False
    export_options: ExportOptions = Field(default_factory=ExportOptions)

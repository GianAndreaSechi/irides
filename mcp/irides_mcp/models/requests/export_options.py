from enum import Enum

from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    OKF = "okf"


class ExportOptions(BaseModel):
    formats: list[ExportFormat] = Field(
        default_factory=lambda: [ExportFormat.MARKDOWN, ExportFormat.OKF]
    )
    preformat: bool = True

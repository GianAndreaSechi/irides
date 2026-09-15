from typing import Optional
from pydantic import BaseModel, Field


class TableRequest(BaseModel):
    config_name: Optional[str] = Field(
        default=None,
        description="Configured database target name, e.g. 'mysql_primary'.",
    )
    instance_name: Optional[str] = Field(
        default=None,
        description=(
            "Database instance returned by list_instances. For MySQL this is "
            "the configured MySQL host. Omit to scan all instances in config_name."
        ),
    )
    schema_name: Optional[str] = Field(
        default=None,
        description="Schema/database name, e.g. 'quality_checks'. Omit to list tables from all schemas.",
    )
    limit: Optional[int] = Field(default=None, description="Maximum number of tables to return.")
    offset: Optional[int] = Field(default=None, description="Number of tables to skip.")

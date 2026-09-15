from typing import Optional
from pydantic import BaseModel, Field


class SchemaRequest(BaseModel):
    config_name: Optional[str] = Field(
        default=None,
        description="Configured database target name, e.g. 'mysql_primary'.",
    )
    instance_name: Optional[str] = Field(
        default=None,
        description="Database instance returned by list_instances. For MySQL this is the configured host.",
    )

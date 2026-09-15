from typing import Optional
from pydantic import BaseModel, Field


class InstanceRequest(BaseModel):
    config_name: Optional[str] = Field(
        default=None,
        description=(
            "Configured database target name, e.g. 'mysql_primary'. "
            "Omit to list instances for all configured targets."
        ),
    )

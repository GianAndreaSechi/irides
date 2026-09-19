from pydantic import BaseModel
from typing import Any, Optional

class GenericResponse(BaseModel):
    message: str
    data: Optional[Any] = None

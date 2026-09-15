from pydantic import BaseModel
from typing import Any, Optional, Union

class GenericResponse(BaseModel):
    message: str
    data: Optional[Any] = None

class ToonResponse(BaseModel):
    """
    Specific response type for TOON formatted data, optimized for LLM consumption.
    """
    toon: str

UnifiedResponse = Union[GenericResponse, ToonResponse]

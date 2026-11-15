import json
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from typing import Any, Optional
from loguru import logger

try:
    import toons  # type: ignore
except ImportError:
    toons = None

from api.irides_api.models.response.generic_response import GenericResponse

def api_response(request: Request, message: str, data: Any, status_code: int = 200):
    """
    Creates a FastAPI response, serializing the data based on the Accept header.
    """
    accept_header = request.headers.get("accept", "application/json")
    logger.info(f"Accept header: {accept_header}")

    response_model = GenericResponse(message=message, data=data)
    response_data = (
        response_model.model_dump()
        if hasattr(response_model, "model_dump")
        else response_model.dict()
    )

    if "application/toon" in accept_header:
        logger.info("Returning TOON response")
        toon_data = toons.dumps(response_data) if toons is not None else json.dumps(response_data)
        return Response(content=toon_data, media_type="application/toon", status_code=status_code)
    else:
        logger.info("Returning JSON response")
        return JSONResponse(content=response_data, status_code=status_code)
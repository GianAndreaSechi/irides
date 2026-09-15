from fastapi import Request
from fastapi.responses import JSONResponse, Response
from typing import Any, Optional
import toons
from loguru import logger

from api.irides_api.models.response.generic_response import GenericResponse

def api_response(request: Request, message: str, data: Any):
    """
    Creates a FastAPI response, serializing the data based on the Accept header.
    """
    accept_header = request.headers.get("accept", "application/json")
    logger.info(f"Accept header: {accept_header}")

    response_data = GenericResponse(message=message, data=data).dict()

    if "application/toon" in accept_header:
        logger.info("Returning TOON response")
        toon_data = toons.dumps(response_data)
        return Response(content=toon_data, media_type="application/toon")
    else:
        logger.info("Returning JSON response")
        return JSONResponse(content=response_data)
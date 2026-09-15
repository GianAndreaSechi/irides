from fastmcp import Context
from loguru import logger
from typing import Optional
from ..services.api_client import api_client
from ..models.responses.generic_response import GenericResponse
from ..constants import TOON_RESPONSE_FORMAT

def register_tools(mcp):
    """Register all car_data tools for the MCP Server"""

    @mcp.tool()
    async def healthz() -> GenericResponse:
        """
        Check the health of the API service by calling the /ping endpoint.
        """
        logger.info("MCP: Checking API health via /ping.")
        api_response = await api_client.get("/ping", response_format=TOON_RESPONSE_FORMAT)
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])
        return GenericResponse(message="API health check successful.", data=api_response.get("data"))
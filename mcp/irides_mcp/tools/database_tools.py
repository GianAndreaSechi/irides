import toons
from fastmcp import Context
from loguru import logger
from typing import Optional, Union
from ..services.api_client import api_client
from ..models.requests.instance_request import InstanceRequest
from ..models.requests.schema_request import SchemaRequest
from ..models.requests.table_request import TableRequest
from ..models.requests.describe_table_request import DescribeTableRequest
from ..models.responses.generic_response import GenericResponse, ToonResponse, UnifiedResponse
from ..constants import TOON_RESPONSE_FORMAT

def register_tools(mcp):
    """Register all database introspection tools for the MCP Server."""

    @mcp.tool()
    async def get_available_connectors(no_cache: Optional[bool] = False) -> UnifiedResponse:
        """
        Get configured database target names from the API service.

        The returned values are config_name values to pass to the other tools,
        for example 'mysql_primary'. They are not network hosts and not
        connector types like 'mysql'.
        """
        logger.info("MCP: Fetching available database configurations from API service.")
        response_format = TOON_RESPONSE_FORMAT
        api_response = await api_client.get("/configurations", no_cache=no_cache, response_format=response_format)
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])
        
        if response_format == TOON_RESPONSE_FORMAT:
            return ToonResponse(toon=toons.dumps(api_response.get("data")))
            
        return GenericResponse(message="Available database configurations retrieved successfully from API.", data=api_response.get("data"))

    @mcp.tool()
    async def list_instances(request: InstanceRequest, no_cache: Optional[bool] = False) -> UnifiedResponse:
        """
        List database instances for configured targets by calling the API service.

        Use config_name for the configured target, e.g. 'mysql_primary'.
        For MySQL, returned instance names are the configured MySQL hosts.
        """
        logger.info(f"MCP: Listing instances for config '{request.config_name}' via API service.")
        response_format = TOON_RESPONSE_FORMAT
        api_response = await api_client.post("/instances", payload=request.model_dump(), no_cache=no_cache, response_format=response_format)
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])

        if response_format == TOON_RESPONSE_FORMAT:
            return ToonResponse(toon=toons.dumps(api_response.get("data")))

        return GenericResponse(message=f"Instances for '{request.config_name}' retrieved successfully from API.", data=api_response.get("data"))

    @mcp.tool()
    async def list_schemas(request: SchemaRequest, no_cache: Optional[bool] = False) -> UnifiedResponse:
        """
        List schemas/databases for a configured target and instance by calling the API service.

        Use config_name for the configured target, e.g. 'mysql_primary'.
        Use instance_name from list_instances; for MySQL this is the configured MySQL host.
        """
        logger.info(f"MCP: Listing schemas for instance '{request.instance_name}' in config '{request.config_name}' via API.")
        response_format = TOON_RESPONSE_FORMAT
        api_response = await api_client.post("/schemas", payload=request.model_dump(), no_cache=no_cache, response_format=response_format)
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])
        
        if response_format == TOON_RESPONSE_FORMAT:
            return ToonResponse(toon=toons.dumps(api_response.get("data")))

        return GenericResponse(message=f"Schemas for instance '{request.instance_name}' retrieved successfully from API.", data=api_response.get("data"))

    @mcp.tool()
    async def list_tables(request: TableRequest, no_cache: Optional[bool] = False) -> UnifiedResponse:
        """
        List tables for a schema/database by calling the API service.

        Use config_name for the configured target, instance_name from list_instances,
        and schema_name for the database/schema, e.g. 'quality_checks'.
        """
        logger.info(f"MCP: Listing tables for schema '{request.schema_name}' in instance '{request.instance_name}' via API.")
        response_format = TOON_RESPONSE_FORMAT
        api_response = await api_client.post("/tables", payload=request.model_dump(), no_cache=no_cache, response_format=response_format)
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])
        
        if response_format == TOON_RESPONSE_FORMAT:
            return ToonResponse(toon=toons.dumps(api_response.get("data")))

        return GenericResponse(message=f"Tables for schema '{request.schema_name}' retrieved successfully from API.", data=api_response.get("data"))

    @mcp.tool()
    async def describe_table(request: DescribeTableRequest, no_cache: Optional[bool] = False) -> UnifiedResponse:
        """
        Describe one or more tables by calling the API service.

        Use config_name for the configured target, instance_name from list_instances,
        schema_name for the database/schema, and table_name for a specific table.
        Set generate_ai_docs=True whenever the user asks for AI analysis,
        AI documentation, business documentation, or an AI-generated explanation.
        Markdown and OKF exports with essential preformatting are enabled by default;
        pass an empty formats list or preformat=False to opt out explicitly.
        """
        logger.info(
            f"MCP: Describing table '{request.table_name}' in schema '{request.schema_name}' via API "
            f"(generate_ai_docs={request.generate_ai_docs}, save_metadata={request.save_metadata}, "
            f"export_options={request.export_options.model_dump(mode='json')})."
        )
        response_format = TOON_RESPONSE_FORMAT
        api_response = await api_client.post("/describe", payload=request.model_dump(), no_cache=no_cache, response_format=response_format)
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])
        
        if response_format == TOON_RESPONSE_FORMAT:
            return ToonResponse(toon=toons.dumps(api_response.get("data")))

        return GenericResponse(message=f"Description for table '{request.table_name}' retrieved successfully from API.", data=api_response.get("data"))

    

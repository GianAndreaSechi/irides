import os
from fastmcp import FastMCP
from loguru import logger
from .models.requests.instance_request import InstanceRequest
from .models.requests.schema_request import SchemaRequest
from .models.requests.table_request import TableRequest
from .models.requests.describe_table_request import DescribeTableRequest
from .models.responses.generic_response import GenericResponse
from .constants import TOON_RESPONSE_FORMAT

from .tools.healtz_tools import register_tools as register_healthz_tools
from .tools.database_tools import register_tools as register_database_tools
from .tools.scan_tools import register_tools as register_scan_tools
from .tools.metadata_tools import register_tools as register_metadata_tools

mcp = FastMCP("Multi-DB Connector Control Plane (MCP)")

register_healthz_tools(mcp)
register_database_tools(mcp)
register_scan_tools(mcp)
register_metadata_tools(mcp)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "http")
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    
    logger.info(f"Starting MCP server with {transport} transport...")
    if transport == "http":
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run(transport="stdio")

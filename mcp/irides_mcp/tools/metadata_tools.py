import urllib.parse
import toons
from loguru import logger
from typing import Optional

from ..services.api_client import api_client
from ..models.responses.generic_response import GenericResponse, ToonResponse, UnifiedResponse
from ..constants import TOON_RESPONSE_FORMAT, JSON_RESPONSE_FORMAT


def _encode_seg(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def register_tools(mcp):
    """
    Register tools for reading and updating STORED metadata.

    These tools operate on metadata that has been previously saved to the metadata
    store (filesystem, and in future S3/Athena). The data reflects the last scan or
    describe operation and MAY have been manually edited by a human via the UI or
    the PATCH API — treat it as a curated, potentially enriched snapshot, not a
    live database query.

    For live database queries (with Redis caching) use the separate tools:
      - list_instances / list_schemas / list_tables / describe_table
    """

    @mcp.tool()
    async def list_stored_instances(
        page: Optional[int] = 1,
        page_size: Optional[int] = 20,
        config_name: Optional[str] = None,
    ) -> UnifiedResponse:
        """
        List all instances that have at least one table saved in the metadata store.

        NOTE: This reads from the metadata store (saved snapshots), NOT from live
        databases. Results reflect what has been catalogued so far and may include
        human-added annotations. Use list_instances for live database discovery.

        Returns a paginated list: { items, total, page, page_size, pages }.
        """
        logger.info(f"MCP: Listing stored metadata instances (page={page}, page_size={page_size}, config_name={config_name})")
        params = f"?page={page}&page_size={page_size}"
        if config_name:
            params += f"&config_name={_encode_seg(config_name)}"
        result = await api_client.get(
            f"/metadata{params}",
            response_format=JSON_RESPONSE_FORMAT,
        )
        if "error" in result:
            return GenericResponse(message=result["error"], error=result["error"])
        return GenericResponse(
            message="Stored instances retrieved successfully.",
            data=result.get("data"),
        )

    @mcp.tool()
    async def list_stored_databases(
        instance_name: str,
        page: Optional[int] = 1,
        page_size: Optional[int] = 20,
        config_name: Optional[str] = None,
    ) -> UnifiedResponse:
        """
        List all databases/schemas saved in the metadata store for a given instance.

        NOTE: This reads from the metadata store (saved snapshots), NOT from a live
        database. The list reflects what has already been scanned and saved.
        Use list_schemas for live discovery.

        Args:
             instance_name: The instance name as it appears in the metadata store
                            (e.g. 'db-primary.example.internal'). Use
                           list_stored_instances to find valid values.

        Returns a paginated list: { items, total, page, page_size, pages }.
        """
        logger.info(f"MCP: Listing stored databases for instance '{instance_name}' (page={page}, config_name={config_name})")
        params = f"?page={page}&page_size={page_size}"
        if config_name:
            params += f"&config_name={_encode_seg(config_name)}"
        result = await api_client.get(
            f"/metadata/{_encode_seg(instance_name)}{params}",
            response_format=JSON_RESPONSE_FORMAT,
        )
        if "error" in result:
            return GenericResponse(message=result["error"], error=result["error"])
        return GenericResponse(
            message=f"Stored databases for '{instance_name}' retrieved successfully.",
            data=result.get("data"),
        )

    @mcp.tool()
    async def list_stored_tables(
        instance_name: str,
        database_name: str,
        page: Optional[int] = 1,
        page_size: Optional[int] = 20,
        config_name: Optional[str] = None,
    ) -> UnifiedResponse:
        """
        List all tables saved in the metadata store for a given instance and database.

        NOTE: This reads from the metadata store (saved snapshots), NOT from a live
        database. Only tables that have been previously described and saved will appear.
        Use list_tables for live discovery.

        Args:
            instance_name: Instance name as it appears in the metadata store.
            database_name: Database/schema name as it appears in the metadata store.

        Returns a paginated list: { items, total, page, page_size, pages }.
        """
        logger.info(f"MCP: Listing stored tables for '{instance_name}/{database_name}' (page={page}, config_name={config_name})")
        params = f"?page={page}&page_size={page_size}"
        if config_name:
            params += f"&config_name={_encode_seg(config_name)}"
        result = await api_client.get(
            f"/metadata/{_encode_seg(instance_name)}/{_encode_seg(database_name)}{params}",
            response_format=JSON_RESPONSE_FORMAT,
        )
        if "error" in result:
            return GenericResponse(message=result["error"], error=result["error"])
        return GenericResponse(
            message=f"Stored tables for '{instance_name}/{database_name}' retrieved successfully.",
            data=result.get("data"),
        )

    @mcp.tool()
    async def get_stored_table_metadata(
        instance_name: str,
        database_name: str,
        table_name: str,
        config_name: Optional[str] = None,
    ) -> UnifiedResponse:
        """
        Retrieve the full stored metadata document for a specific table.

        IMPORTANT: This document is a saved snapshot and may differ from the live
        database schema. It can contain:
          - schema_description: columns, keys, indexes from the last scan/describe
          - ai_documentation: AI-generated or human-edited business summary and
                              column descriptions
          - Any custom fields added manually by a human (e.g. owner, tags, notes)

        Do NOT use this as a substitute for describe_table when you need the current
        live schema — use it when you want the enriched, annotated version of the
        table that the team has curated.

        Args:
            instance_name: Instance name (e.g. 'db-primary.example.internal').
            database_name: Database/schema name (e.g. 'example_schema').
            table_name:    Table name (e.g. 'example_table').
            config_name:   Optional configuration name to disambiguate colliding targets.
        """
        logger.info(f"MCP: Getting stored metadata for '{instance_name}/{database_name}/{table_name}' (config_name={config_name})")
        params = f"?config_name={_encode_seg(config_name)}" if config_name else ""
        result = await api_client.get(
            f"/metadata/{_encode_seg(instance_name)}/{_encode_seg(database_name)}/{_encode_seg(table_name)}{params}",
            response_format=TOON_RESPONSE_FORMAT,
        )
        if "error" in result:
            return GenericResponse(message=result["error"], error=result["error"])
        return ToonResponse(toon=toons.dumps(result.get("data")))

    @mcp.tool()
    async def update_stored_table_metadata(
        instance_name: str,
        database_name: str,
        table_name: str,
        fields: dict,
        config_name: Optional[str] = None,
    ) -> UnifiedResponse:
        """
        Merge custom fields into the stored metadata document for a specific table.

        Use this to enrich the metadata document with human knowledge: business
        context, ownership, tags, quality notes, or corrections to AI documentation.
        Changes are merged (not replaced) into the existing document.

        Protected fields that cannot be overwritten:
          metadata_key, config_name, instance_name, schema_name, table_name, updated_at

        Example payload:
          {
            "owner": "data-team",
            "tags": ["pii", "critical"],
            "ai_documentation": { "summary": "Updated business summary..." }
          }

        Args:
            instance_name: Instance name in the metadata store.
            database_name: Database/schema name in the metadata store.
            table_name:    Table name in the metadata store.
            fields:        Dict of fields to merge into the document.
            config_name:   Optional configuration name to disambiguate colliding targets.
        """
        logger.info(
            f"MCP: Updating stored metadata for '{instance_name}/{database_name}/{table_name}' "
            f"(config_name={config_name}) with fields: {list(fields.keys())}"
        )
        params = f"?config_name={_encode_seg(config_name)}" if config_name else ""
        result = await api_client.patch(
            f"/metadata/{_encode_seg(instance_name)}/{_encode_seg(database_name)}/{_encode_seg(table_name)}{params}",
            payload=fields,
            response_format=JSON_RESPONSE_FORMAT,
        )
        if "error" in result:
            return GenericResponse(message=result["error"], error=result["error"])
        return GenericResponse(
            message=f"Stored metadata for '{table_name}' updated successfully.",
            data=result.get("data"),
        )

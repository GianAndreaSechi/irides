from fastapi import APIRouter, Body, HTTPException, Query, Request
from typing import Any, Dict

from api.irides_api.services.metadata_service import MetadataService
from api.irides_api.services.response_service import api_response
from core.db_connector.storage import get_metadata_store

router = APIRouter(prefix="/metadata", tags=["metadata"])

_metadata_service = MetadataService(get_metadata_store())


@router.get("")
async def list_instances(
    http_request: Request,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=200, description="Items per page"),
):
    """List all instances that have stored metadata, paginated."""
    data = _metadata_service.list_instances(page=page, page_size=page_size)
    return api_response(http_request, "Instances retrieved successfully.", data)


@router.get("/{instance}")
async def list_databases(
    instance: str,
    http_request: Request,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=200, description="Items per page"),
):
    """List all databases/schemas for a given instance, paginated."""
    data = _metadata_service.list_databases(instance=instance, page=page, page_size=page_size)
    if data["total"] == 0:
        raise HTTPException(status_code=404, detail=f"No metadata found for instance '{instance}'.")
    return api_response(http_request, "Databases retrieved successfully.", data)


@router.get("/{instance}/{database}")
async def list_tables(
    instance: str,
    database: str,
    http_request: Request,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=200, description="Items per page"),
):
    """List all tables for a given instance+database, paginated."""
    data = _metadata_service.list_tables(instance=instance, database=database, page=page, page_size=page_size)
    if data["total"] == 0:
        raise HTTPException(status_code=404, detail=f"No metadata found for '{instance}/{database}'.")
    return api_response(http_request, "Tables retrieved successfully.", data)


@router.get("/{instance}/{database}/{table}")
async def get_table_detail(
    instance: str,
    database: str,
    table: str,
    http_request: Request,
):
    """Return the full stored metadata JSON for a specific table."""
    data = _metadata_service.get_table(instance=instance, database=database, table=table)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No metadata found for '{instance}/{database}/{table}'.")
    return api_response(http_request, "Table metadata retrieved successfully.", data)


@router.patch("/{instance}/{database}/{table}")
async def update_table_metadata(
    instance: str,
    database: str,
    table: str,
    http_request: Request,
    payload: Dict[str, Any] = Body(..., description="Fields to merge into the metadata document. System identity fields (metadata_key, config_name, instance_name, schema_name, table_name, updated_at) are protected and cannot be overwritten."),
):
    """Merge custom fields into an existing table metadata document.

    Protected fields: metadata_key, config_name, instance_name, schema_name, table_name, updated_at.
    """
    if not payload:
        raise HTTPException(status_code=422, detail="Payload must not be empty.")
    data = _metadata_service.update_table(instance=instance, database=database, table=table, payload=payload)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No metadata found for '{instance}/{database}/{table}'.")
    return api_response(http_request, "Table metadata updated successfully.", data)

from fastapi import APIRouter, FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional, Dict, Any, List
from pathlib import Path
from pydantic import BaseModel
from loguru import logger
from datetime import datetime, timezone
import asyncio
import os

_STATIC_DIR = Path(__file__).parent / "static"
_UI_FILE = _STATIC_DIR / "index.html"

from core.db_connector.manager import ConnectorManager
from core.db_connector.models import (
    Instance, Schema, Table,
    TableDescription
)
from core.db_connector.cache_manager import CacheManager
from core.db_connector.config_service import ConfigService
from api.irides_api.services.instance_service import InstanceService
from api.irides_api.services.schema_service import SchemaService
from api.irides_api.services.table_service import TableService
from api.irides_api.services.describe_table_service import DescribeTableService

from api.irides_api.models.requests.connection_request import ConnectionRequest
from api.irides_api.models.requests.instance_request import InstanceRequest
from api.irides_api.models.requests.schema_request import SchemaRequest
from api.irides_api.models.requests.table_request import TableRequest
from api.irides_api.models.requests.describe_table_request import DescribeTableRequest
from api.irides_api.models.requests.scan_request import ScanRequest
from api.irides_api.services.response_service import api_response
from api.irides_api.services.scan_service import ScanService
from core.db_connector.job_store import JobStore
from api.irides_api.routers.metadata_router import router as metadata_router

app = FastAPI(
    title="Multi DB Describer API",
    description="API for connecting to various databases and performing introspection.",
    version="0.2.0",
)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Initialize CacheManager
cache_manager = CacheManager(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=int(os.getenv("REDIS_DB", 0)),
    ttl_seconds=int(os.getenv("REDIS_TTL_SECONDS", 86400)), # Default 1 day
    socket_connect_timeout=float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 2)),
    socket_timeout=float(os.getenv("REDIS_CACHE_SOCKET_TIMEOUT_SECONDS", 2)),
)

# Initialize ConnectorManager and Services
connector_manager = ConnectorManager(cache_manager)
config_service = ConfigService(connector_manager)
instance_service = InstanceService(config_service, connector_manager)
schema_service = SchemaService(config_service, connector_manager)
table_service = TableService(config_service, connector_manager)
describe_table_service = DescribeTableService(config_service, connector_manager)

job_store = JobStore(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=int(os.getenv("REDIS_DB", 0)),
    prefix=os.getenv("CACHE_KEY_PREFIX", "multi-db-connector"),
    socket_connect_timeout=float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 2)),
)
scan_service = ScanService(job_store, config_service)

# Helper to extract no_cache header
def get_no_cache_header(no_cache: Optional[str] = Header(None)) -> bool:
    return no_cache is not None and no_cache.lower() == "true"

# ---------------------------------------------------------------------------
# v1 router — all business routes live here
# ---------------------------------------------------------------------------

v1 = APIRouter(prefix="/api/v1")

@v1.get("/")
async def read_root(http_request: Request):
    logger.info("Root endpoint accessed.")
    return api_response(http_request, "Welcome to the Multi-DB Connector API!", None)

@v1.get("/ping")
async def ping(http_request: Request):
    logger.info("Ping endpoint accessed.")
    return api_response(
        http_request,
        "Pong!",
        {"status": "success", "timestamp": datetime.now(timezone.utc).isoformat()},
    )

@v1.get("/configurations")
async def get_available_configurations(http_request: Request, no_cache: bool = Depends(get_no_cache_header)):
    """
    Get a list of all available database configurations.
    """
    logger.info("API: Fetching available configurations.")
    data = config_service.get_available_configurations()
    return api_response(http_request, "Available configurations retrieved successfully.", data)

@v1.post("/connect")
async def test_connection(req: ConnectionRequest, http_request: Request):
    """
    Test a connection to a specified database configuration.
    """
    logger.info(f"API: Attempting to test connection for config: {req.config_name}")
    try:
        data = config_service.test_connection(req.config_name)
        return api_response(http_request, "Connection test successful.", data)
    except ValueError as e:
        logger.error(f"API: Connection test failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as e:
        logger.error(f"API: Connection test failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")
    except Exception as e:
        logger.exception(f"API: An unexpected error occurred during connection test for config: {req.config_name}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")

@v1.post("/instances")
async def list_instances_route(req: InstanceRequest, http_request: Request, no_cache: bool = Depends(get_no_cache_header)):
    """
    List all instances (e.g., hosts for MySQL, database files for SQLite)
    for a given connector type. If no connector types are specified,
    instances for all available connector types will be returned.
    """
    logger.info(f"API: Listing instances for config name: {req.config_name}")
    try:
        config_names = [req.config_name] if req.config_name else None
        data = instance_service.list_instances(config_names, no_cache=no_cache)
        return api_response(http_request, "Instances retrieved successfully.", data)
    except ValueError as e:
        logger.error(f"API: Listing instances failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as e:
        logger.error(f"API: Listing instances failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")
    except Exception as e:
        logger.exception(f"API: An unexpected error occurred while listing instances for config name: {req.config_name}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")

@v1.post("/schemas")
async def list_schemas_route(req: SchemaRequest, http_request: Request, no_cache: bool = Depends(get_no_cache_header)):
    """
    List all schemas (databases) for a given instance and configuration.
    If config_name is not specified, lists schemas for all available configurations.
    If instance_name is not specified, lists schemas for all instances within the specified configuration(s).
    """
    logger.info(f"API: Listing schemas for config: {req.config_name if req.config_name else 'all'}, instance: {req.instance_name if req.instance_name else 'all'}")
    try:
        data = schema_service.list_schemas(req.config_name, req.instance_name, no_cache=no_cache)
        return api_response(http_request, "Schemas retrieved successfully.", data)
    except ValueError as e:
        logger.error(f"API: Listing schemas failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as e:
        logger.error(f"API: Listing schemas failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")
    except Exception as e:
        logger.exception(f"API: An unexpected error occurred while listing schemas for config: {req.config_name}, instance: {req.instance_name}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")

@v1.post("/tables")
async def list_tables_route(req: TableRequest, http_request: Request, no_cache: bool = Depends(get_no_cache_header)):
    """
    List all tables for a given schema, instance, and configuration.
    If config_name is not specified, lists tables for all available configurations.
    If instance_name is not specified, lists tables for all instances within the specified configuration(s).
    If schema_name is not specified, lists tables for all schemas within the specified instance(s).
    """
    logger.info(f"API: Listing tables for config: {req.config_name if req.config_name else 'all'}, instance: {req.instance_name if req.instance_name else 'all'}, schema: {req.schema_name if req.schema_name else 'all'}, limit: {req.limit if req.limit else 'none'}, offset: {req.offset if req.offset else 'none'}")
    try:
        data = table_service.list_tables(req.config_name, req.instance_name, req.schema_name, req.limit, req.offset, no_cache=no_cache)
        return api_response(http_request, "Tables retrieved successfully.", data)
    except ValueError as e:
        logger.error(f"API: Listing tables failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as e:
        logger.error(f"API: Listing tables failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")
    except Exception as e:
        logger.exception(f"API: An unexpected error occurred while listing tables for config: {req.config_name}, instance: {req.instance_name}, schema: {req.schema_name}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")

@v1.post("/describe")
async def describe_table_route(req: DescribeTableRequest, http_request: Request, no_cache: bool = Depends(get_no_cache_header)):
    """
    Get a detailed description of a specific table, including columns,
    primary keys, foreign keys, and other indexes.
    If config_name is not specified, describes tables for all available configurations.
    If instance_name is not specified, describes tables for all instances within the specified configuration(s).
    If schema_name is not specified, describes tables for all schemas within the specified instance(s).
    If table_name is not specified, describes all tables within the specified schema(s).
    """
    logger.info(
        f"API: Describing table for config: {req.config_name if req.config_name else 'all'}, "
        f"instance: {req.instance_name if req.instance_name else 'all'}, "
        f"schema: {req.schema_name if req.schema_name else 'all'}, "
        f"table: {req.table_name if req.table_name else 'all'}, "
        f"generate_ai_docs={req.generate_ai_docs}, save_metadata={req.save_metadata}, "
        f"only_if_changed={req.only_if_changed}, export_options={req.export_options.model_dump(mode='json')}"
    )
    try:
        data = await asyncio.to_thread(
            describe_table_service.describe_table,
            req.config_name,
            req.instance_name,
            req.schema_name,
            req.table_name,
            no_cache=no_cache,
            generate_ai_docs=req.generate_ai_docs,
            save_metadata=req.save_metadata,
            only_if_changed=req.only_if_changed,
            export_options=req.export_options,
        )
        return api_response(http_request, "Table description retrieved successfully.", data)
    except ValueError as e:
        logger.error(f"API: Describing table failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as e:
        logger.error(f"API: Describing table failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")
    except Exception as e:
        logger.exception(f"API: An unexpected error occurred while describing table for config: {req.config_name}, instance: {req.instance_name}, schema: {req.schema_name}, table: {req.table_name}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


# ---------------------------------------------------------------------------
# Async scan endpoints
# ---------------------------------------------------------------------------

@v1.post("/scan", status_code=202)
async def enqueue_scan(req: ScanRequest, http_request: Request, no_cache: bool = Depends(get_no_cache_header)):
    """
    Enqueue an async scan job.
    The worker will describe all tables matching the given scope and store results.
    Returns a job_id that can be polled via GET /scan/{job_id}.

    Scope resolution (all None = scan everything):
    - config_name=None   → all configurations
    - instance_name=None → all instances within each config
    - schema_name=None   → all schemas within each instance
    """
    logger.info(
        f"API: Enqueuing scan job config={req.config_name}, "
        f"instance={req.instance_name}, schema={req.schema_name}, no_cache={no_cache}, "
        f"generate_ai_docs={req.generate_ai_docs}, save_metadata={req.save_metadata}, "
        f"only_if_changed={req.only_if_changed}, export_options={req.export_options.model_dump(mode='json')}"
    )
    try:
        job = scan_service.enqueue_scan(
            req.config_name,
            req.instance_name,
            req.schema_name,
            no_cache=no_cache,
            generate_ai_docs=req.generate_ai_docs,
            save_metadata=req.save_metadata,
            only_if_changed=req.only_if_changed,
            export_options=req.export_options,
        )
        return api_response(http_request, "Scan job enqueued successfully.", job.model_dump(mode="json"))

    except ConnectionError as e:
        logger.error(f"API: Scan enqueue failed — Redis unreachable: {e}")
        raise HTTPException(status_code=503, detail=f"Queue unavailable: {e}")
    except ValueError as e:
        logger.error(f"API: Scan enqueue rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("API: Unexpected error while enqueuing scan job")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


@v1.get("/scan/{job_id}")
async def get_scan_job(job_id: str, http_request: Request, include_results: bool = False):
    """
    Get the status (and optionally results) of a scan job.
    Add ?include_results=true to retrieve the full list of TableDescriptions.
    """
    try:
        job = scan_service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Scan job '{job_id}' not found.")

        data = job.model_dump(mode="json")
        if include_results:
            data["results"] = scan_service.get_job_results(job_id)

        return api_response(http_request, "Scan job retrieved successfully.", data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"API: Unexpected error retrieving scan job {job_id}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


@v1.get("/scans")
async def list_scan_jobs(http_request: Request, limit: int = 50):
    """
    List recent scan jobs (newest first, no results payload).
    """
    try:
        jobs = scan_service.list_jobs(limit=limit)
        return api_response(
            http_request,
            "Scan jobs retrieved successfully.",
            [j.model_dump(mode="json") for j in jobs],
        )
    except Exception as e:
        logger.exception("API: Unexpected error listing scan jobs")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


v1.include_router(metadata_router)
app.include_router(v1)


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui():
    return _UI_FILE.read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.irides_api.main:app", host="0.0.0.0", port=8000)

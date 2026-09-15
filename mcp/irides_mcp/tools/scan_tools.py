import toons
from loguru import logger
from typing import Optional

from ..services.api_client import api_client
from ..models.requests.scan_request import ScanRequest
from ..models.responses.generic_response import GenericResponse, ToonResponse, UnifiedResponse
from ..constants import TOON_RESPONSE_FORMAT, JSON_RESPONSE_FORMAT


def register_tools(mcp):
    """Register async scan tools for the MCP Server."""

    @mcp.tool()
    async def enqueue_scan(request: ScanRequest, no_cache: Optional[bool] = False) -> UnifiedResponse:
        """
        Enqueue an async scan job.
        The worker will describe all tables matching the given scope and store results in Redis.
        Returns a job_id to poll via get_scan_job.

        Scope (all optional — omit to scan everything):
          - config_name:   limit to a specific DB configuration
          - instance_name: limit to a specific instance within the config
          - schema_name:   limit to a specific schema within the instance

        Options:
          - generate_ai_docs: generate a business summary and column descriptions via the configured LLM.
            Set this to True whenever the user asks for AI analysis,
            AI documentation, business documentation, or an AI-generated explanation.
          - save_metadata: persist generated metadata to the configured storage.
          - export_options: Markdown and OKF with essential preformatting are enabled by default.
            Pass formats=[] or preformat=False to opt out explicitly.
        
        Cache:
          - no_cache: if True, bypasses existing cache and forces a fresh scan.
        """
        logger.info(
            f"MCP: Enqueueing scan job "
            f"[config={request.config_name}, instance={request.instance_name}, schema={request.schema_name}, "
            f"generate_ai_docs={request.generate_ai_docs}, save_metadata={request.save_metadata}, "
            f"export_options={request.export_options.model_dump(mode='json')}, no_cache={no_cache}]"
        )
        api_response = await api_client.post(
            "/scan",
            payload=request.model_dump(),
            no_cache=no_cache,
            response_format=JSON_RESPONSE_FORMAT,
        )
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])

        return GenericResponse(
            message="Scan job enqueued. Use get_scan_job(job_id) to poll status.",
            data=api_response.get("data"),
        )

    @mcp.tool()
    async def get_scan_job(job_id: str, include_results: Optional[bool] = False) -> UnifiedResponse:
        """
        Get the status of a scan job by job_id.
        Set include_results=True to also retrieve the full list of TableDescriptions.

        Possible statuses: pending | running | completed | partial | failed
        """
        logger.info(f"MCP: Getting scan job {job_id} (include_results={include_results})")
        endpoint = f"/scan/{job_id}?include_results={str(include_results).lower()}"
        api_response = await api_client.get(endpoint, response_format=JSON_RESPONSE_FORMAT)
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])

        data = api_response.get("data", {})

        # If results are included, compress them as TOON for LLM efficiency
        if include_results and data.get("results"):
            results = data.pop("results")
            return ToonResponse(toon=toons.dumps({"job": data, "results": results}))

        return GenericResponse(message="Scan job retrieved successfully.", data=data)

    @mcp.tool()
    async def list_scan_jobs(limit: Optional[int] = 20) -> UnifiedResponse:
        """
        List recent scan jobs (newest first), without result payloads.
        Use get_scan_job(job_id) to fetch details or results for a specific job.
        """
        logger.info(f"MCP: Listing scan jobs (limit={limit})")
        api_response = await api_client.get(
            f"/scans?limit={limit}",
            response_format=JSON_RESPONSE_FORMAT,
        )
        if "error" in api_response:
            return GenericResponse(message=api_response["error"])

        return GenericResponse(message="Scan jobs retrieved successfully.", data=api_response.get("data"))

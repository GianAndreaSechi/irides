import os
from loguru import logger
import httpx
from typing import Optional, Dict, Any
import toons
from ..constants import TOON_RESPONSE_FORMAT, JSON_RESPONSE_FORMAT

class ApiClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_prefix: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = base_url or os.getenv("API_BASE_URL", "http://localhost:8000")
        self.api_prefix = api_prefix or os.getenv("API_PREFIX", "/api/v1")
        resolved_timeout = (
            timeout
            if timeout is not None
            else float(os.getenv("MCP_API_TIMEOUT_SECONDS", "120.0"))
        )
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=resolved_timeout)

    def _url(self, endpoint: str) -> str:
        return f"{self.api_prefix}{endpoint}"

    def _build_headers(self, no_cache: bool, response_format: str, content_type: Optional[str] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if no_cache:
            headers["no-cache"] = "true"
        api_key = os.getenv("IRIDES_API_KEY")
        if api_key:
            headers["X-API-Key"] = api_key
        headers["Accept"] = (
            "application/toon" if response_format == TOON_RESPONSE_FORMAT else "application/json"
        )
        return headers

    async def post(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        no_cache: bool = False,
        response_format: str = JSON_RESPONSE_FORMAT,
        raw_toon: bool = False,
    ) -> Dict[str, Any]:
        """
        Makes a POST request to the specified endpoint.
        """
        headers = self._build_headers(no_cache, response_format, content_type="application/json")

        try:
            response = await self.client.post(self._url(endpoint), json=payload, headers=headers)
            response.raise_for_status()
            if response_format == TOON_RESPONSE_FORMAT:
                decoded = response.content.decode("utf-8")
                if raw_toon:
                    return {"toon": decoded}
                return toons.loads(decoded)
            else:
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API Client: Error calling {endpoint}: {e.response.status_code} - {e.response.text}")
            return {"error": f"API error: {e.response.text}"}
        except httpx.RequestError as e:
            logger.error(f"API Client: Network error calling {endpoint}: {e}")
            return {"error": f"Network error connecting to API: {e}"}
        except Exception as e:
            logger.exception(f"API Client: An unexpected error occurred while calling {endpoint}.")
            return {"error": f"An unexpected error occurred: {e}"}

    async def patch(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        response_format: str = JSON_RESPONSE_FORMAT,
        raw_toon: bool = False,
    ) -> Dict[str, Any]:
        """Makes a PATCH request to the specified endpoint."""
        headers = self._build_headers(False, response_format, content_type="application/json")

        try:
            response = await self.client.patch(self._url(endpoint), json=payload, headers=headers)
            response.raise_for_status()
            if response_format == TOON_RESPONSE_FORMAT:
                decoded = response.content.decode("utf-8")
                if raw_toon:
                    return {"toon": decoded}
                return toons.loads(decoded)
            else:
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API Client: Error calling {endpoint}: {e.response.status_code} - {e.response.text}")
            return {"error": f"API error: {e.response.text}"}
        except httpx.RequestError as e:
            logger.error(f"API Client: Network error calling {endpoint}: {e}")
            return {"error": f"Network error connecting to API: {e}"}
        except Exception as e:
            logger.exception(f"API Client: An unexpected error occurred while calling {endpoint}.")
            return {"error": f"An unexpected error occurred: {e}"}

    async def get(
        self,
        endpoint: str,
        no_cache: bool = False,
        response_format: str = JSON_RESPONSE_FORMAT,
        raw_toon: bool = False,
    ) -> Dict[str, Any]:
        """
        Makes a GET request to the specified endpoint.
        """
        headers = self._build_headers(no_cache, response_format)

        try:
            response = await self.client.get(self._url(endpoint), headers=headers)
            response.raise_for_status()
            if response_format == TOON_RESPONSE_FORMAT:
                decoded = response.content.decode("utf-8")
                if raw_toon:
                    return {"toon": decoded}
                return toons.loads(decoded)
            else:
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API Client: Error calling {endpoint}: {e.response.status_code} - {e.response.text}")
            return {"error": f"API error: {e.response.text}"}
        except httpx.RequestError as e:
            logger.error(f"API Client: Network error calling {endpoint}: {e}")
            return {"error": f"Network error connecting to API: {e}"}
        except Exception as e:
            logger.exception(f"API Client: An unexpected error occurred while calling {endpoint}.")
            return {"error": f"An unexpected error occurred: {e}"}

api_client = ApiClient()

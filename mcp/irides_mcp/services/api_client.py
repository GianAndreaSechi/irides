import os
from loguru import logger
import httpx
from typing import Optional, Dict, Any
import toons
from ..constants import TOON_RESPONSE_FORMAT, JSON_RESPONSE_FORMAT

class ApiClient:
    def __init__(self, base_url: Optional[str] = None, api_prefix: Optional[str] = None):
        self.base_url = base_url or os.getenv("API_BASE_URL", "http://localhost:8000")
        self.api_prefix = api_prefix or os.getenv("API_PREFIX", "/api/v1")
        self.client = httpx.AsyncClient(base_url=self.base_url)

    def _url(self, endpoint: str) -> str:
        return f"{self.api_prefix}{endpoint}"

    async def post(self, endpoint: str, payload: Dict[str, Any], no_cache: bool = False, response_format: str = JSON_RESPONSE_FORMAT) -> Dict[str, Any]:
        """
        Makes a POST request to the specified endpoint.
        """
        headers = {"Content-Type": "application/json"}
        if no_cache:
            headers["no-cache"] = "true"

        if response_format == TOON_RESPONSE_FORMAT:
            headers["Accept"] = "application/toon"
        else:
            headers["Accept"] = "application/json"

        try:
            response = await self.client.post(self._url(endpoint), json=payload, headers=headers)
            response.raise_for_status()
            if response_format == TOON_RESPONSE_FORMAT:
                return toons.loads(response.content.decode("utf-8"))
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

    async def patch(self, endpoint: str, payload: Dict[str, Any], response_format: str = JSON_RESPONSE_FORMAT) -> Dict[str, Any]:
        """Makes a PATCH request to the specified endpoint."""
        headers = {"Content-Type": "application/json"}
        if response_format == TOON_RESPONSE_FORMAT:
            headers["Accept"] = "application/toon"
        else:
            headers["Accept"] = "application/json"

        try:
            response = await self.client.patch(self._url(endpoint), json=payload, headers=headers)
            response.raise_for_status()
            if response_format == TOON_RESPONSE_FORMAT:
                return toons.loads(response.content.decode("utf-8"))
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

    async def get(self, endpoint: str, no_cache: bool = False, response_format: str = JSON_RESPONSE_FORMAT) -> Dict[str, Any]:
        """
        Makes a GET request to the specified endpoint.
        """
        headers = {}
        if no_cache:
            headers["no-cache"] = "true"

        if response_format == TOON_RESPONSE_FORMAT:
            headers["Accept"] = "application/toon"
        else:
            headers["Accept"] = "application/json"

        try:
            response = await self.client.get(self._url(endpoint), headers=headers)
            response.raise_for_status()
            if response_format == TOON_RESPONSE_FORMAT:
                return toons.loads(response.content.decode("utf-8"))
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

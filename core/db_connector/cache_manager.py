import hashlib
import json
import os
from typing import Any, Optional
from loguru import logger
import redis


def hash_auth_context(*parts: Optional[str]) -> str:
    """Return a short non-reversible fingerprint for user/account/endpoint context."""
    raw = ":".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


class CacheManager:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        ttl_seconds: int = 86400,
        project_prefix: Optional[str] = None,
        socket_connect_timeout: float = 2.0,
        socket_timeout: float = 2.0,
        enabled: bool = True,
    ):
        self.redis_client = None
        self.ttl_seconds = ttl_seconds  # Default 1 day
        self.enabled = enabled
        self.project_prefix = (
            project_prefix
            if project_prefix is not None
            else os.getenv("CACHE_KEY_PREFIX", "multi-db-connector")
        )
        if not self.enabled:
            return
        try:
            self.redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_connect_timeout=socket_connect_timeout,
                socket_timeout=socket_timeout,
                health_check_interval=30,
            )
            self.redis_client.ping()
            logger.info(f"Successfully connected to Redis at {host}:{port}/{db}")
        except redis.exceptions.RedisError as e:
            logger.error(f"Could not connect to Redis cache at {host}:{port}/{db}: {e}")
            self.redis_client = None  # Ensure client is None if connection fails

    def _serialize(self, data: Any) -> str:
        """Serializes data to JSON string."""
        return json.dumps(data)

    def _deserialize(self, data_str: str) -> Any:
        """Deserializes JSON string to data."""
        return json.loads(data_str)

    def get_cached_data(self, key: str, no_cache: bool = False) -> Optional[Any]:
        prefixed_key = f"{self.project_prefix}:{key}"
        if not self.enabled or not self.redis_client or no_cache:
            return None
        try:
            cached_data = self.redis_client.get(prefixed_key)
            if cached_data:
                logger.debug(f"Cache hit for key: {prefixed_key}")
                return self._deserialize(cached_data)
            logger.debug(f"Cache miss for key: {prefixed_key}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving data from Redis for key {prefixed_key}: {e}")
            return None

    def set_cached_data(self, key: str, data: Any, ttl: Optional[int] = None) -> None:
        prefixed_key = f"{self.project_prefix}:{key}"
        if not self.enabled or not self.redis_client:
            return
        try:
            ttl_to_use = ttl if ttl is not None else self.ttl_seconds
            self.redis_client.setex(prefixed_key, ttl_to_use, self._serialize(data))
            logger.debug(f"Data set in cache for key: {prefixed_key} with TTL: {ttl_to_use}s")
        except Exception as e:
            logger.error(f"Error setting data in Redis for key {prefixed_key}: {e}")


class NullCacheManager(CacheManager):
    """No-op cache manager that never attempts network connections."""

    def __init__(self, project_prefix: Optional[str] = None):
        super().__init__(project_prefix=project_prefix, enabled=False)

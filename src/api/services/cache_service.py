"""Redis cache service with cache-aside pattern."""
import hashlib
import json
from typing import Any

from src.api.core.config import Settings
from src.api.core.logging import get_logger

logger = get_logger(__name__)


class CacheService:
    """Redis cache service with graceful degradation (cache-aside pattern).

    If Redis is unavailable, cache operations log warning and continue
    without cache. This prevents cache failures from breaking requests.
    """

    def __init__(self, settings: Settings):
        """Initialize cache service.

        Args:
            settings: Application settings with Redis configuration.
        """
        self.settings = settings
        self.client = None

    async def connect(self) -> None:
        """Initialize async Redis client.

        Errors are logged but not raised (cache optional).
        """
        try:
            import redis.asyncio as redis

            self.client = await redis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )

            # Test connectivity
            await self.client.ping()
            logger.info("redis_cache_connected", redis_url=self.settings.redis_url)

        except Exception as e:
            logger.warning("redis_cache_connection_failed", error=str(e))
            self.client = None  # Cache disabled

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            logger.info("redis_cache_disconnected")

    def _cache_key(self, prefix: str, **kwargs: Any) -> str:
        """Generate deterministic cache key from parameters.

        Params are sorted and SHA-256 hashed for stable keys.

        Args:
            prefix: Cache key prefix (e.g. 'query:by-app').
            **kwargs: Query parameters.

        Returns:
            Cache key string: 'cache:prefix:{sha256(sorted params)}'.
        """
        # Sort kwargs for determinism
        sorted_items = sorted((k, str(v)) for k, v in kwargs.items())
        params_str = json.dumps(sorted_items)
        params_hash = hashlib.sha256(params_str.encode()).hexdigest()[:16]
        return f"cache:{prefix}:{params_hash}"

    async def get_cached(self, key: str) -> dict[str, Any] | None:
        """Get value from cache.

        Args:
            key: Cache key.

        Returns:
            Parsed JSON dict or None if not found or Redis unavailable.
        """
        if not self.client:
            return None

        try:
            value = await self.client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning("cache_get_error", key=key, error=str(e))
            return None

    async def set_cached(self, key: str, data: dict[str, Any], ttl: int = 60) -> bool:
        """Set value in cache with TTL.

        Args:
            key: Cache key.
            data: Data to cache (will be JSON serialized).
            ttl: Time-to-live in seconds (default 60).

        Returns:
            True if set successfully, False if Redis unavailable.
        """
        if not self.client:
            return False

        try:
            json_str = json.dumps(data)
            await self.client.setex(key, ttl, json_str)
            return True
        except Exception as e:
            logger.warning("cache_set_error", key=key, ttl=ttl, error=str(e))
            return False

    async def delete_cached(self, key: str) -> bool:
        """Delete value from cache.

        Args:
            key: Cache key.

        Returns:
            True if deleted, False if not found or error.
        """
        if not self.client:
            return False

        try:
            result = await self.client.delete(key)
            return bool(result)
        except Exception as e:
            logger.warning("cache_delete_error", key=key, error=str(e))
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern (development only).

        Args:
            pattern: Redis key pattern (e.g. 'cache:query:*').

        Returns:
            Number of keys deleted.
        """
        if not self.client:
            return 0

        try:
            keys = await self.client.keys(pattern)
            if keys:
                deleted = await self.client.delete(*keys)
                logger.info("cache_pattern_cleared", pattern=pattern, deleted=deleted)
                return deleted
            return 0
        except Exception as e:
            logger.warning("cache_clear_pattern_error", pattern=pattern, error=str(e))
            return 0

    async def health(self) -> tuple[bool, str]:
        """Check Redis health.

        Returns:
            Tuple (is_healthy, status_message).
        """
        if not self.client:
            return False, "Redis not initialized"

        try:
            result = await self.client.ping()
            return bool(result), "Redis healthy"
        except Exception as e:
            return False, f"Redis unavailable: {str(e)}"

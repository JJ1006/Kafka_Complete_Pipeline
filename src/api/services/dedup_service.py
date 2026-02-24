"""Redis deduplication service using atomic SETNX operations."""

import hashlib
import json
from typing import Any

import redis.asyncio as redis

from src.api.core.config import Settings
from src.api.core.logging import get_logger
from src.api.core.metrics import record_dedup_check
from src.api.core.telemetry import traced_operation

logger = get_logger(__name__)


class RedisDeduplicationService:
    """Handles transactional deduplication via Redis atomic SETNX."""

    def __init__(self, settings: Settings):
        """Initialize Redis dedup service.

        Args:
            settings: Application settings with REDIS_URL.
        """
        self.settings = settings
        self.client: redis.Redis[bytes] | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self.client = await redis.from_url(
            self.settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("redis_connected", url=self.settings.redis_url)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self.client:
            await self.client.close()
            logger.info("redis_disconnected")

    @traced_operation("dedup.check_and_set")
    async def check_and_set(
        self, application_number: str, request_id: str, ttl_seconds: int = 86400
    ) -> bool:
        """Check if transaction is duplicate and set if new (atomic SETNX).

        Uses Redis SET with NX (set if not exists) flag for atomic operation
        across multiple FastAPI replicas.

        Args:
            application_number: Unique application identifier.
            request_id: Idempotency key for this transaction.
            ttl_seconds: Time-to-live for dedup key (default 24h).

        Returns:
            True if this is a NEW transaction (key was set), False if DUPLICATE.

        Raises:
            Exception: If Redis connection fails.
        """
        import time

        if not self.client:
            logger.error("redis_not_connected")
            raise RuntimeError("Redis client not initialized")

        # Build deterministic key: dedup:{SHA256(app+req)}
        composite = f"{application_number}:{request_id}"
        key_hash = hashlib.sha256(composite.encode()).hexdigest()
        dedup_key = f"dedup:{key_hash}"

        start_time = time.monotonic()

        try:
            # Atomic SET with NX (only if key doesn't exist) + EX (expiry)
            result = await self.client.set(dedup_key, "1", nx=True, ex=ttl_seconds)

            duration_seconds = time.monotonic() - start_time

            if result:  # SET succeeded (key was new)
                record_dedup_check(result="new", duration_seconds=duration_seconds)
                logger.info(
                    "dedup_new_tx",
                    application_number=application_number,
                    request_id=request_id,
                    dedup_key=dedup_key,
                )
                return True
            else:  # SET failed (key already exists)
                record_dedup_check(result="duplicate", duration_seconds=duration_seconds)
                logger.info(
                    "dedup_duplicate_tx",
                    application_number=application_number,
                    request_id=request_id,
                    dedup_key=dedup_key,
                )
                return False

        except Exception as e:
            duration_seconds = time.monotonic() - start_time
            record_dedup_check(result="error", duration_seconds=duration_seconds)
            logger.error("redis_dedup_error", error=str(e), dedup_key=dedup_key, exc_info=True)
            raise

    async def cache_idempotency_response(
        self, idempotency_key: str, response_body: dict[str, Any], ttl_seconds: int = 86400
    ) -> None:
        """Cache idempotency key response for identical retries.

        Args:
            idempotency_key: Unique idempotency key from request header.
            response_body: The 202 response to cache as JSON.
            ttl_seconds: Cache TTL (default 24h).
        """
        if not self.client:
            logger.error("redis_not_connected")
            return

        cache_key = f"idem:{idempotency_key}"

        try:
            await self.client.set(cache_key, json.dumps(response_body), ex=ttl_seconds)
            logger.info("idempotency_cached", idempotency_key=idempotency_key)
        except Exception as e:
            logger.error("idempotency_cache_error", idempotency_key=idempotency_key, error=str(e))

    async def get_cached_response(self, idempotency_key: str) -> dict[str, Any] | None:
        """Retrieve cached response for idempotency key.

        Args:
            idempotency_key: Unique idempotency key from request header.

        Returns:
            Cached response body dict if found, None otherwise.
        """
        if not self.client:
            return None

        cache_key = f"idem:{idempotency_key}"

        try:
            result = await self.client.get(cache_key)
            if result:
                logger.info("idempotency_hit", idempotency_key=idempotency_key)
                return json.loads(result)
            return None
        except Exception as e:
            logger.error(
                "idempotency_retrieve_error", idempotency_key=idempotency_key, error=str(e)
            )
            return None

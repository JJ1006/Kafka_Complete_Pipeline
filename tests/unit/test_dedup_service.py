"""Unit tests for RedisDeduplicationService."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.api.core.config import get_settings
from src.api.services.dedup_service import RedisDeduplicationService


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def dedup_service(settings):
    service = RedisDeduplicationService(settings)
    service.client = AsyncMock()
    return service


@pytest.fixture
def disconnected_dedup_service(settings):
    service = RedisDeduplicationService(settings)
    service.client = None
    return service


@pytest.mark.asyncio
async def test_dedup_connect(dedup_service):
    with patch("redis.asyncio.from_url", new_callable=AsyncMock) as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        await dedup_service.connect()
        assert dedup_service.client is not None


@pytest.mark.asyncio
async def test_dedup_disconnect(dedup_service):
    await dedup_service.disconnect()
    dedup_service.client.close.assert_called_once()


@pytest.mark.asyncio
async def test_dedup_disconnect_no_client(disconnected_dedup_service):
    await disconnected_dedup_service.disconnect()  # Should not raise


@pytest.mark.asyncio
async def test_check_and_set_new_transaction(dedup_service):
    """A new transaction returns True."""
    dedup_service.client.set.return_value = True
    result = await dedup_service.check_and_set("APP-001", "REQ-001")
    assert result is True
    dedup_service.client.set.assert_called_once()


@pytest.mark.asyncio
async def test_check_and_set_duplicate_transaction(dedup_service):
    """A duplicate transaction returns False."""
    dedup_service.client.set.return_value = None  # Redis NX returns None on duplicate
    result = await dedup_service.check_and_set("APP-001", "REQ-001")
    assert result is False


@pytest.mark.asyncio
async def test_check_and_set_no_client(disconnected_dedup_service):
    """RuntimeError when client not initialized."""
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        await disconnected_dedup_service.check_and_set("APP-001", "REQ-001")


@pytest.mark.asyncio
async def test_check_and_set_redis_error(dedup_service):
    """Redis exception propagates."""
    dedup_service.client.set.side_effect = Exception("Redis connection failed")
    with pytest.raises(Exception, match="Redis connection failed"):
        await dedup_service.check_and_set("APP-001", "REQ-001")


@pytest.mark.asyncio
async def test_cache_idempotency_response_success(dedup_service):
    """Caches idempotency response successfully."""
    response = {"key": "APP-001:req1", "message": "ok"}
    dedup_service.client.set.return_value = True
    await dedup_service.cache_idempotency_response("idem-001", response)
    dedup_service.client.set.assert_called_once()


@pytest.mark.asyncio
async def test_cache_idempotency_response_no_client(disconnected_dedup_service):
    """No-op when client not available."""
    await disconnected_dedup_service.cache_idempotency_response("idem-001", {"key": "val"})


@pytest.mark.asyncio
async def test_cache_idempotency_response_redis_error(dedup_service):
    """Errors are caught gracefully, not raised."""
    dedup_service.client.set.side_effect = Exception("Redis error")
    # Should NOT raise - errors are swallowed
    await dedup_service.cache_idempotency_response("idem-001", {"key": "val"})


@pytest.mark.asyncio
async def test_get_cached_response_hit(dedup_service):
    """Returns cached response on hit."""
    cached = {"composite_key": "APP-001:req1"}
    dedup_service.client.get.return_value = json.dumps(cached)
    result = await dedup_service.get_cached_response("idem-001")
    assert result == cached


@pytest.mark.asyncio
async def test_get_cached_response_miss(dedup_service):
    """Returns None on cache miss."""
    dedup_service.client.get.return_value = None
    result = await dedup_service.get_cached_response("idem-001")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_response_no_client(disconnected_dedup_service):
    result = await disconnected_dedup_service.get_cached_response("idem-001")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_response_redis_error(dedup_service):
    dedup_service.client.get.side_effect = Exception("Redis error")
    result = await dedup_service.get_cached_response("idem-001")
    assert result is None

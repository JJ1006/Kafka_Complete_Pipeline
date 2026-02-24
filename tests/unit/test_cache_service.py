"""Unit tests for CacheService."""

from unittest.mock import AsyncMock, patch

import pytest

from src.api.core.config import get_settings
from src.api.services.cache_service import CacheService


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def cache_service(settings):
    service = CacheService(settings)
    service.client = AsyncMock()
    return service


@pytest.fixture
def disconnected_cache_service(settings):
    """A service with no client connected."""
    service = CacheService(settings)
    service.client = None
    return service


@pytest.mark.asyncio
async def test_cache_connect(cache_service):
    with patch("redis.asyncio.from_url", new_callable=AsyncMock) as mock_from_url:
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_from_url.return_value = mock_client

        await cache_service.connect()
        assert cache_service.client is not None


@pytest.mark.asyncio
async def test_cache_disconnect(cache_service):
    await cache_service.disconnect()
    cache_service.client.close.assert_called_once()


@pytest.mark.asyncio
async def test_cache_disconnect_no_client(disconnected_cache_service):
    """Test that disconnect gracefully handles no client."""
    await disconnected_cache_service.disconnect()  # Should not raise


@pytest.mark.asyncio
async def test_cache_health(cache_service):
    cache_service.client.ping.return_value = True
    healthy, msg = await cache_service.health()
    assert healthy is True
    assert msg == "Redis healthy"


@pytest.mark.asyncio
async def test_cache_health_no_client(disconnected_cache_service):
    healthy, msg = await disconnected_cache_service.health()
    assert healthy is False
    assert "not initialized" in msg


@pytest.mark.asyncio
async def test_cache_health_redis_error(cache_service):
    cache_service.client.ping.side_effect = Exception("Redis unreachable")
    healthy, msg = await cache_service.health()
    assert healthy is False
    assert "Redis unavailable" in msg


@pytest.mark.asyncio
async def test_get_cached_hit(cache_service):
    import json

    data = {"key": "value"}
    cache_service.client.get.return_value = json.dumps(data)
    result = await cache_service.get_cached("test_key")
    assert result == data


@pytest.mark.asyncio
async def test_get_cached_miss(cache_service):
    cache_service.client.get.return_value = None
    result = await cache_service.get_cached("test_key")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_no_client(disconnected_cache_service):
    result = await disconnected_cache_service.get_cached("test_key")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_redis_error(cache_service):
    cache_service.client.get.side_effect = Exception("Redis error")
    result = await cache_service.get_cached("test_key")
    assert result is None


@pytest.mark.asyncio
async def test_set_cached_success(cache_service):
    cache_service.client.setex.return_value = True
    result = await cache_service.set_cached("test_key", {"data": "val"}, ttl=30)
    assert result is True
    cache_service.client.setex.assert_called_once()


@pytest.mark.asyncio
async def test_set_cached_no_client(disconnected_cache_service):
    result = await disconnected_cache_service.set_cached("test_key", {"data": "val"})
    assert result is False


@pytest.mark.asyncio
async def test_set_cached_redis_error(cache_service):
    cache_service.client.setex.side_effect = Exception("Redis error")
    result = await cache_service.set_cached("test_key", {"data": "val"})
    assert result is False


@pytest.mark.asyncio
async def test_delete_cached_success(cache_service):
    cache_service.client.delete.return_value = 1
    result = await cache_service.delete_cached("test_key")
    assert result is True


@pytest.mark.asyncio
async def test_delete_cached_no_client(disconnected_cache_service):
    result = await disconnected_cache_service.delete_cached("test_key")
    assert result is False


@pytest.mark.asyncio
async def test_delete_cached_redis_error(cache_service):
    cache_service.client.delete.side_effect = Exception("Redis error")
    result = await cache_service.delete_cached("test_key")
    assert result is False


@pytest.mark.asyncio
async def test_clear_pattern_success(cache_service):
    cache_service.client.keys.return_value = ["key1", "key2"]
    cache_service.client.delete.return_value = 2
    result = await cache_service.clear_pattern("cache:*")
    assert result == 2


@pytest.mark.asyncio
async def test_clear_pattern_no_keys(cache_service):
    cache_service.client.keys.return_value = []
    result = await cache_service.clear_pattern("cache:*")
    assert result == 0


@pytest.mark.asyncio
async def test_clear_pattern_no_client(disconnected_cache_service):
    result = await disconnected_cache_service.clear_pattern("cache:*")
    assert result == 0


def test_cache_key_deterministic(cache_service):
    key1 = cache_service._cache_key("prefix", a="1", b="2")
    key2 = cache_service._cache_key("prefix", b="2", a="1")
    assert key1 == key2
    assert key1.startswith("cache:prefix:")

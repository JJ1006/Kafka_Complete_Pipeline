from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


def test_validation_error_handler():
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from src.api.core.config import get_settings
    from src.api.routers.transactions import get_dedup_service, get_kafka_producer, require_api_key

    app.dependency_overrides[require_api_key] = lambda: "dummy"
    app.dependency_overrides[get_dedup_service] = lambda: AsyncMock()
    app.dependency_overrides[get_kafka_producer] = lambda: AsyncMock()
    app.dependency_overrides[get_settings] = lambda: AsyncMock()

    with (
        patch("src.api.main.KafkaProducerService.connect", new_callable=AsyncMock),
        patch("src.api.main.RedisDeduplicationService.connect", new_callable=AsyncMock),
        patch("src.api.main.ElasticsearchService.connect", new_callable=AsyncMock),
        patch("src.api.main.CacheService.connect", new_callable=AsyncMock),
    ):
        with TestClient(app, raise_server_exceptions=True) as client:
            headers = {"X-API-Key": "dummy", "Host": "testclient"}
            response = client.post("/transactions", json={}, headers=headers)

    assert response.status_code == 422
    data = response.json()
    assert data["status"] == 422
    assert data["title"] == "Validation Failed"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_general_exception_handler():
    # Force a general exception in health endpoint which doesn't require auth
    with patch("src.api.routers.health.logger.info", side_effect=Exception("Database down")):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testclient") as client:
            response = await client.get("/health", headers={"X-Trace-ID": "trace-123"})

            assert response.status_code == 500
            data = response.json()
            assert data["trace_id"] == "trace-123"
            assert data["title"] == "Internal Server Error"

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


@pytest.mark.asyncio
async def test_health_check_success():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testclient"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "timestamp" in data
    assert data["dependencies"]["kafka"]["status"] == "healthy"
    assert data["dependencies"]["elasticsearch"]["status"] == "healthy"
    assert data["dependencies"]["redis"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_check_failure(mocker):
    # health.py currently hardcodes success inside the route function and doesn't call external methods
    # We will simulate failure by making logger.info raise an exception to hit the general Exception block in the route
    mocker.patch("src.api.routers.health.logger.info", side_effect=Exception("Database down"))

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testclient") as client:
        # Note: exceptions in routes might be caught by main.py's exception handler
        response = await client.get("/health")

    # Because main.py catches general exceptions and returns a 500 error response:
    assert response.status_code == 500
    data = response.json()
    assert data["status"] == 500
    assert data["title"] == "Internal Server Error"

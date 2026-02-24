import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


@pytest.mark.asyncio
async def test_root_endpoint():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testclient"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Credit Transaction Platform API",
        "docs": "/docs",
        "ui": "/ui",
    }


@pytest.mark.asyncio
async def test_ui_routing_no_spa():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testclient"
    ) as client:
        response = await client.get("/ui")

    # Assuming SPA index.html is not actually built, we expect 404
    assert response.status_code == 404
    assert response.json() == {"detail": "SPA not built"}


@pytest.mark.asyncio
async def test_ui_routing_path_missing():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testclient"
    ) as client:
        response = await client.get("/ui/some/subpath")

    assert response.status_code == 404
    assert response.json() == {"detail": "SPA not built"}

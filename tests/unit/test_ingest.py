"""Unit tests for transaction ingest endpoint."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client() -> TestClient:
    """Fixture for FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def valid_transaction() -> dict[str, Any]:
    """Fixture for valid transaction payload."""
    return {
        "application_number": "APP-001",
        "request_id": "REQ-001",
        "transunion_score": 720,
        "loan_amount": 50000.00,
        "tenure_months": 60,
        "interest_rate_apr": 8.5,
        "employment_type": "Salaried",
        "product_type": "PersonalLoan",
        "customer_city": "New York",
        "income_monthly": 5000.00,
        "existing_debt": 10000.00,
    }


@pytest.fixture
def headers_with_api_key() -> dict[str, str]:
    """Fixture for request headers with valid API key."""
    return {
        "X-API-Key": "test-api-key-12345",
        "X-Correlation-ID": "corr-123",
        "X-Trace-ID": "trace-123",
    }


@pytest.mark.asyncio
async def test_ingest_valid_transaction_async(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test successful transaction ingest returns 202 Accepted (async)."""
    from httpx import AsyncClient

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Mock the global services
        from src.api.routers import transactions

        # Create mock services
        mock_dedup = AsyncMock()
        mock_dedup.check_and_set.return_value = True
        mock_dedup.get_cached_response.return_value = None

        mock_producer = AsyncMock()
        mock_producer.produce_transaction.return_value = "0"

        # Set services
        transactions.set_services(mock_dedup, mock_producer)

        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["composite_key"] == f"{valid_transaction['application_number']}:*"
        assert "ingested_at" in data
        assert data["correlation_id"] == headers_with_api_key["X-Correlation-ID"]
        assert data["trace_id"] == headers_with_api_key["X-Trace-ID"]


@pytest.mark.asyncio
async def test_ingest_duplicate_transaction(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test duplicate transaction returns 409 Conflict."""
    from httpx import AsyncClient

    from src.api.routers import transactions

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Create mock services
        mock_dedup = AsyncMock()
        mock_dedup.check_and_set.return_value = False  # Duplicate!
        mock_dedup.get_cached_response.return_value = None

        mock_producer = AsyncMock()

        # Set services
        transactions.set_services(mock_dedup, mock_producer)

        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "Duplicate transaction" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_missing_api_key(valid_transaction: dict[str, Any]) -> None:
    """Test missing API key returns 401 Unauthorized."""
    from httpx import AsyncClient

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/transactions", json=valid_transaction)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "X-API-Key header required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_missing_required_field(headers_with_api_key: dict[str, str]) -> None:
    """Test missing required field returns 422 Unprocessable Entity."""
    from httpx import AsyncClient

    # Missing application_number
    invalid_transaction = {
        "request_id": "REQ-001",
        "transunion_score": 720,
        "loan_amount": 50000.00,
        "tenure_months": 60,
        "interest_rate_apr": 8.5,
        "employment_type": "Salaried",
        "product_type": "PersonalLoan",
    }

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=invalid_transaction, headers=headers_with_api_key
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_ingest_invalid_credit_score(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test invalid credit score (outside 300-900 range) returns 422."""
    from httpx import AsyncClient

    invalid_transaction = valid_transaction.copy()
    invalid_transaction["transunion_score"] = 250  # Below minimum

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=invalid_transaction, headers=headers_with_api_key
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_ingest_invalid_employment_type(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test invalid employment type returns 422."""
    from httpx import AsyncClient

    invalid_transaction = valid_transaction.copy()
    invalid_transaction["employment_type"] = "InvalidType"

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=invalid_transaction, headers=headers_with_api_key
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_ingest_with_idempotency_key_new(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test ingest with idempotency key (new request) caches response."""
    from httpx import AsyncClient

    from src.api.routers import transactions

    headers = headers_with_api_key.copy()
    headers["X-Idempotency-Key"] = "idem-001"

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Create mock services
        mock_dedup = AsyncMock()
        mock_dedup.check_and_set.return_value = True
        mock_dedup.get_cached_response.return_value = None
        mock_dedup.cache_idempotency_response.return_value = None

        mock_producer = AsyncMock()
        mock_producer.produce_transaction.return_value = "0"

        # Set services
        transactions.set_services(mock_dedup, mock_producer)

        response = await ac.post("/transactions", json=valid_transaction, headers=headers)

        assert response.status_code == status.HTTP_202_ACCEPTED
        # Verify cache_idempotency_response was called
        assert mock_dedup.cache_idempotency_response.called


@pytest.mark.asyncio
async def test_ingest_with_idempotency_key_cached(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test ingest with idempotency key (cached) returns cached response."""
    from httpx import AsyncClient

    from src.api.routers import transactions

    headers = headers_with_api_key.copy()
    headers["X-Idempotency-Key"] = "idem-001"

    # Mock cached response
    cached_response = {
        "composite_key": "APP-001:cached-request-id",
        "ingested_at": datetime.now(UTC).isoformat(),
        "correlation_id": "cached-corr",
        "trace_id": "cached-trace",
        "message": "Transaction accepted for processing",
    }

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Create mock services
        mock_dedup = AsyncMock()
        mock_dedup.get_cached_response.return_value = cached_response

        mock_producer = AsyncMock()

        # Set services
        transactions.set_services(mock_dedup, mock_producer)

        response = await ac.post("/transactions", json=valid_transaction, headers=headers)

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["composite_key"] == cached_response["composite_key"]
        # Verify producer was NOT called (cached response)
        assert not mock_producer.produce_transaction.called


@pytest.mark.asyncio
async def test_ingest_kafka_producer_unavailable(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test Kafka producer unavailable returns 503 Service Unavailable."""
    from httpx import AsyncClient

    from src.api.routers import transactions

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Create mock services
        mock_dedup = AsyncMock()
        mock_dedup.check_and_set.return_value = True
        mock_dedup.get_cached_response.return_value = None

        # Mock producer that raises exception
        mock_producer = AsyncMock()
        mock_producer.produce_transaction.side_effect = Exception("Kafka broker unreachable")

        # Set services
        transactions.set_services(mock_dedup, mock_producer)

        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_ingest_dedup_service_unavailable(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test dedup service unavailable returns 503."""
    from httpx import AsyncClient

    from src.api.routers import transactions

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Set services to None (simulating unavailable)
        transactions._dedup_service = None  # type: ignore

        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

"""Unit tests for transaction ingest endpoint."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.api.routers import transactions


def build_app(
    dedup_service: Any = None,
    kafka_producer: Any = None,
) -> FastAPI:
    """Build a minimal FastAPI app with mocked services for unit tests.

    Services are injected directly via set_services() — no lifespan needed.
    """
    # Wire mocked services into the scoped globals before building app
    transactions.set_services(dedup_service, kafka_producer)

    app = FastAPI(title="Test App", version="1.0.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(transactions.router)

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Strip 'ctx' field which may contain non-JSON-serializable Python objects
        safe_errors = [{k: v for k, v in e.items() if k != "ctx"} for e in exc.errors()]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": safe_errors},
        )

    return app


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
    """Test successful transaction ingest returns 202 Accepted."""
    mock_dedup = AsyncMock()
    mock_dedup.check_and_set.return_value = True
    mock_dedup.get_cached_response.return_value = None

    mock_producer = AsyncMock()
    mock_producer.produce_transaction.return_value = "0"

    app = build_app(dedup_service=mock_dedup, kafka_producer=mock_producer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert data["composite_key"].startswith(valid_transaction["application_number"])
    assert "ingested_at" in data
    assert data["correlation_id"] == headers_with_api_key["X-Correlation-ID"]
    assert data["trace_id"] == headers_with_api_key["X-Trace-ID"]


@pytest.mark.asyncio
async def test_ingest_duplicate_transaction(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test duplicate transaction returns 409 Conflict."""
    mock_dedup = AsyncMock()
    mock_dedup.check_and_set.return_value = False  # Duplicate!
    mock_dedup.get_cached_response.return_value = None

    mock_producer = AsyncMock()
    app = build_app(dedup_service=mock_dedup, kafka_producer=mock_producer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Duplicate transaction" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_missing_api_key(valid_transaction: dict[str, Any]) -> None:
    """Test missing API key returns 401 Unauthorized."""
    app = build_app(dedup_service=AsyncMock(), kafka_producer=AsyncMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/transactions", json=valid_transaction)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "X-API-Key header required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_missing_required_field(headers_with_api_key: dict[str, str]) -> None:
    """Test missing required field (application_number) returns 422."""
    invalid_transaction = {
        "request_id": "REQ-001",
        "transunion_score": 720,
        "loan_amount": 50000.00,
        "tenure_months": 60,
        "interest_rate_apr": 8.5,
        "employment_type": "Salaried",
        "product_type": "PersonalLoan",
    }
    app = build_app(dedup_service=AsyncMock(), kafka_producer=AsyncMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=invalid_transaction, headers=headers_with_api_key
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_ingest_invalid_credit_score(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test invalid credit score (outside 300-900 range) returns 422."""
    bad = valid_transaction.copy()
    bad["transunion_score"] = 250  # Below minimum

    app = build_app(dedup_service=AsyncMock(), kafka_producer=AsyncMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/transactions", json=bad, headers=headers_with_api_key)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_ingest_credit_score_max_boundary(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test credit score at max boundary (900) succeeds → 202."""
    mock_dedup = AsyncMock()
    mock_dedup.check_and_set.return_value = True
    mock_dedup.get_cached_response.return_value = None
    mock_producer = AsyncMock()
    mock_producer.produce_transaction.return_value = "0"

    boundary = valid_transaction.copy()
    boundary["transunion_score"] = 900  # Max allowed

    app = build_app(dedup_service=mock_dedup, kafka_producer=mock_producer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/transactions", json=boundary, headers=headers_with_api_key)

    assert response.status_code == status.HTTP_202_ACCEPTED


@pytest.mark.asyncio
async def test_ingest_invalid_employment_type(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test invalid employment type returns 422."""
    bad = valid_transaction.copy()
    bad["employment_type"] = "InvalidType"

    app = build_app(dedup_service=AsyncMock(), kafka_producer=AsyncMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/transactions", json=bad, headers=headers_with_api_key)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_ingest_with_idempotency_key_new(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test ingest with idempotency key (new request) caches response → 202."""
    headers = headers_with_api_key.copy()
    headers["X-Idempotency-Key"] = "idem-001"

    mock_dedup = AsyncMock()
    mock_dedup.check_and_set.return_value = True
    mock_dedup.get_cached_response.return_value = None
    mock_dedup.cache_idempotency_response.return_value = None

    mock_producer = AsyncMock()
    mock_producer.produce_transaction.return_value = "0"

    app = build_app(dedup_service=mock_dedup, kafka_producer=mock_producer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/transactions", json=valid_transaction, headers=headers)

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert mock_dedup.cache_idempotency_response.called


@pytest.mark.asyncio
async def test_ingest_with_idempotency_key_cached(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test ingest with cached idempotency key returns cached 202 (no Kafka call)."""
    headers = headers_with_api_key.copy()
    headers["X-Idempotency-Key"] = "idem-001"

    cached_response = {
        "composite_key": "APP-001:cached-request-id",
        "ingested_at": datetime.now(UTC).isoformat(),
        "correlation_id": "cached-corr",
        "trace_id": "cached-trace",
        "message": "Transaction accepted for processing",
    }

    mock_dedup = AsyncMock()
    mock_dedup.get_cached_response.return_value = cached_response
    mock_producer = AsyncMock()

    app = build_app(dedup_service=mock_dedup, kafka_producer=mock_producer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/transactions", json=valid_transaction, headers=headers)

    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert data["composite_key"] == cached_response["composite_key"]
    assert not mock_producer.produce_transaction.called  # No Kafka call on cache hit


@pytest.mark.asyncio
async def test_ingest_kafka_producer_unavailable(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test Kafka producer failure returns 503 Service Unavailable."""
    mock_dedup = AsyncMock()
    mock_dedup.check_and_set.return_value = True
    mock_dedup.get_cached_response.return_value = None

    mock_producer = AsyncMock()
    mock_producer.produce_transaction.side_effect = Exception("Kafka broker unreachable")

    app = build_app(dedup_service=mock_dedup, kafka_producer=mock_producer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_ingest_dedup_service_unavailable(
    valid_transaction: dict[str, Any], headers_with_api_key: dict[str, str]
) -> None:
    """Test dedup service None (not initialized) returns 503."""
    # Pass None to simulate uninitialized service
    app = build_app(dedup_service=None, kafka_producer=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/transactions", json=valid_transaction, headers=headers_with_api_key
        )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

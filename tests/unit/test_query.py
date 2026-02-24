"""Unit tests for query and retrieval endpoints (Phase 6)."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.api.models import PaginatedResponse, TransactionResponse
from src.api.routers import query

# ── Helpers ──────────────────────────────────────────────────────────────────


def build_query_app(
    es_service: AsyncMock | None = None,
    cache_service: AsyncMock | None = None,
) -> FastAPI:
    """Minimal FastAPI app with mocked ES + cache services for unit tests."""
    query.set_services(es_service, cache_service)

    app = FastAPI(title="Query Test App", version="1.0.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(query.router)

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        safe_errors = [{k: v for k, v in e.items() if k != "ctx"} for e in exc.errors()]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": safe_errors},
        )

    return app


def make_es_mock(tx: TransactionResponse | None = None) -> AsyncMock:
    """Return a pre-configured ES mock for a single object."""
    es = AsyncMock()
    es.get_transaction.return_value = tx
    return es


def make_cache_miss() -> AsyncMock:
    """Cache that always misses."""
    c = AsyncMock()
    c.get_cached.return_value = None
    c.set_cached.return_value = True
    c._cache_key = MagicMock(return_value="test-cache-key")
    return c


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_transaction() -> TransactionResponse:
    return TransactionResponse(
        application_number="APP001",
        request_id="REQ001",
        transunion_score=720,
        loan_amount=50000.00,
        tenure_months=60,
        interest_rate_apr=7.5,
        employment_type="Salaried",
        product_type="PersonalLoan",
        customer_city="New York",
        income_monthly=5000.0,
        existing_debt=10000.0,
        ingested_at=datetime(2025, 2, 23, 12, 0, 0, tzinfo=UTC),
        schema_version="1.0",
        source="credit-api",
    )


@pytest.fixture
def sample_paginated(sample_transaction: TransactionResponse) -> PaginatedResponse:
    return PaginatedResponse(
        data=[sample_transaction],
        total=1,
        page=1,
        page_size=20,
        total_pages=1,
        has_next=False,
        has_previous=False,
        query_time_ms=10,
        cache_status="MISS",
    )


HEADERS = {"X-API-Key": "test-key"}


# ── Tests: GET /transactions/{app}/{req} ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_transaction_success(sample_transaction: TransactionResponse) -> None:
    """Cache miss → ES hit → 200."""
    es = make_es_mock(tx=sample_transaction)
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/transactions/APP001/REQ001", headers=HEADERS)

    assert r.status_code == 200
    data = r.json()
    assert data["application_number"] == "APP001"
    assert data["transunion_score"] == 720


@pytest.mark.asyncio
async def test_get_transaction_not_found() -> None:
    """Cache miss → ES returns None → 404."""
    es = make_es_mock(tx=None)
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/transactions/APP999/REQ999", headers=HEADERS)

    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_transaction_missing_api_key(sample_transaction: TransactionResponse) -> None:
    """Missing X-API-Key → 401."""
    es = make_es_mock(tx=sample_transaction)
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/transactions/APP001/REQ001")  # no header

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_transaction_cache_hit(sample_transaction: TransactionResponse) -> None:
    """Cache hit → TransactionResponse returned without ES call."""
    es = make_es_mock(tx=sample_transaction)
    cache = AsyncMock()
    cache._cache_key = MagicMock(return_value="hit-key")
    cache.get_cached.return_value = sample_transaction.model_dump(mode="json")

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/transactions/APP001/REQ001", headers=HEADERS)

    assert r.status_code == 200
    assert r.json()["application_number"] == "APP001"
    es.get_transaction.assert_not_called()


@pytest.mark.asyncio
async def test_get_transaction_es_error() -> None:
    """ES raises exception → 503."""
    es = AsyncMock()
    es.get_transaction.side_effect = RuntimeError("ES connection failed")
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/transactions/APP001/REQ001", headers=HEADERS)

    assert r.status_code == 503


# ── Tests: GET /transactions (List) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_transactions_success(
    sample_paginated: PaginatedResponse,
) -> None:
    """List by appNumber → 200 with pagination fields."""
    es = AsyncMock()
    es.list_by_application.return_value = sample_paginated
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            "/transactions?application_number=APP001&page=1&pageSize=20", headers=HEADERS
        )

    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["data"]) == 1


@pytest.mark.asyncio
async def test_pagination_metadata() -> None:
    """Paginated response metadata is passed through."""
    paginated = PaginatedResponse(
        data=[],
        total=250,
        page=2,
        page_size=20,
        total_pages=13,
        has_next=True,
        has_previous=True,
        query_time_ms=15,
        cache_status="MISS",
    )
    es = AsyncMock()
    es.list_by_application.return_value = paginated
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            "/transactions?application_number=APP001&page=2&pageSize=20", headers=HEADERS
        )

    assert r.status_code == 200
    d = r.json()
    assert d["page"] == 2
    assert d["has_next"] is True
    assert d["has_previous"] is True
    assert d["total_pages"] == 13


# ── Tests: GET /transactions/range ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_range_query_success(sample_paginated: PaginatedResponse) -> None:
    """Valid date range → 200."""
    es = AsyncMock()
    es.range_query.return_value = sample_paginated
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            "/transactions/range?from_date=2025-01-01T00:00:00Z&to_date=2025-02-01T00:00:00Z",
            headers=HEADERS,
        )

    assert r.status_code == 200
    assert r.json()["total"] == 1


@pytest.mark.asyncio
async def test_range_query_invalid_date_format() -> None:
    """Malformed date string → 400 (ValueError in date parse)."""
    # Python 3.11+ accepts YYYY-MM-DD, so use a truly malformed string.
    es = AsyncMock()
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            "/transactions/range?from_date=not-a-date&to_date=also-not-a-date",
            headers=HEADERS,
        )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_range_query_with_filters(sample_paginated: PaginatedResponse) -> None:
    """Range query with optional filters calls ES with filters."""
    es = AsyncMock()
    es.range_query.return_value = sample_paginated
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            (
                "/transactions/range"
                "?from_date=2025-01-01T00:00:00Z&to_date=2025-02-01T00:00:00Z"
                "&employment_type=Salaried&product_type=PersonalLoan&score_min=700&score_max=800"
            ),
            headers=HEADERS,
        )

    assert r.status_code == 200
    es.range_query.assert_called_once()


@pytest.mark.asyncio
async def test_range_query_large_result_set() -> None:
    """> 10000 results still returns 200 (logs warning, no error)."""
    large = PaginatedResponse(
        data=[],
        total=15000,
        page=1,
        page_size=20,
        total_pages=750,
        has_next=True,
        has_previous=False,
        query_time_ms=50,
        cache_status="MISS",
    )
    es = AsyncMock()
    es.range_query.return_value = large
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            "/transactions/range?from_date=2025-01-01T00:00:00Z&to_date=2025-03-31T00:00:00Z",
            headers=HEADERS,
        )

    assert r.status_code == 200
    assert r.json()["total"] == 15000


# ── Tests: GET /transactions/download ────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_csv_success(sample_transaction: TransactionResponse) -> None:
    """CSV download: 200, correct content-type, header row present."""

    async def _scroll(*args, **kwargs):
        yield sample_transaction

    es = AsyncMock()
    es.scroll_for_download = _scroll  # real async generator, not coroutine
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            (
                "/transactions/download"
                "?from_date=2025-01-01T00:00:00Z&to_date=2025-02-01T00:00:00Z&format=csv"
            ),
            headers=HEADERS,
        )

    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "application_number" in r.text  # header row present


@pytest.mark.asyncio
async def test_download_jsonl_success(sample_transaction: TransactionResponse) -> None:
    """JSONL download: 200, each line is valid JSON."""

    async def _scroll(*args, **kwargs):
        yield sample_transaction

    es = AsyncMock()
    es.scroll_for_download = _scroll  # real async generator
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            (
                "/transactions/download"
                "?from_date=2025-01-01T00:00:00Z&to_date=2025-02-01T00:00:00Z&format=jsonl"
            ),
            headers=HEADERS,
        )

    assert r.status_code == 200
    assert "ndjson" in r.headers["content-type"]
    for line in r.text.strip().split("\n"):
        if line:
            json.loads(line)  # must be valid JSON


@pytest.mark.asyncio
async def test_download_invalid_format() -> None:
    """Unsupported format → 400."""
    es = AsyncMock()
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            (
                "/transactions/download"
                "?from_date=2025-01-01T00:00:00Z&to_date=2025-02-01T00:00:00Z&format=xml"
            ),
            headers=HEADERS,
        )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_download_invalid_date() -> None:
    """Malformed date string in download → 400 (ValueError in date parse)."""

    async def _scroll(*args, **kwargs):
        return
        yield  # make it an async generator

    es = AsyncMock()
    es.scroll_for_download = _scroll
    cache = make_cache_miss()

    app = build_query_app(es_service=es, cache_service=cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(
            "/transactions/download?from_date=not-a-date&to_date=also-bad&format=csv",
            headers=HEADERS,
        )

    assert r.status_code == 400

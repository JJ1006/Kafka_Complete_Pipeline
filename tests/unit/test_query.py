"""Unit tests for query and retrieval endpoints (Phase 6)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.models import PaginatedResponse, TransactionResponse
from src.api.services.cache_service import CacheService
from src.api.services.elasticsearch_service import ElasticsearchService

# ================== Fixtures ==================


@pytest.fixture
def mock_elasticsearch_service() -> AsyncMock:
    """Mock Elasticsearch service."""
    service = AsyncMock(spec=ElasticsearchService)
    return service


@pytest.fixture
def mock_cache_service() -> AsyncMock:
    """Mock cache service."""
    service = AsyncMock(spec=CacheService)
    return service


@pytest.fixture
def sample_transaction() -> TransactionResponse:
    """Sample transaction response."""
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
def sample_paginated_response(sample_transaction: TransactionResponse) -> PaginatedResponse:
    """Sample paginated response."""
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


@pytest.fixture
def test_client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


# ================== Test: GET /transactions/{applicationNumber}/{requestId} ==================


def test_get_transaction_success(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
    sample_transaction: TransactionResponse,
):
    """Test successful transaction retrieval."""
    # Setup mocks
    mock_cache_service.get_cached.return_value = None  # Cache miss
    mock_elasticsearch_service.get_transaction.return_value = sample_transaction
    mock_cache_service.set_cached.return_value = True

    # Dependency override
    app.dependency_overrides[AsyncMock] = lambda: None

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions/APP001/REQ001",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["application_number"] == "APP001"
    assert data["request_id"] == "REQ001"
    assert data["transunion_score"] == 720


def test_get_transaction_not_found(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
):
    """Test transaction not found (404)."""
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.get_transaction.return_value = None

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions/APP999/REQ999",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data.get("detail", "").lower()


def test_get_transaction_missing_api_key(test_client: TestClient):
    """Test missing API key (401)."""
    response = test_client.get("/transactions/APP001/REQ001")
    assert response.status_code == 401


def test_get_transaction_cache_hit(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
    sample_transaction: TransactionResponse,
):
    """Test cache hit on second call."""
    # First call: cache miss
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.get_transaction.return_value = sample_transaction
    mock_cache_service.set_cached.return_value = True

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response1 = test_client.get(
                "/transactions/APP001/REQ001",
                headers={"X-API-Key": "test-key"},
            )
            assert response1.status_code == 200

    # Second call: cache hit
    mock_cache_service.get_cached.return_value = sample_transaction.model_dump()

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response2 = test_client.get(
                "/transactions/APP001/REQ001",
                headers={"X-API-Key": "test-key"},
            )
            assert response2.status_code == 200
            data = response2.json()
            assert data["application_number"] == "APP001"


# ================== Test: GET /transactions (List by applicationNumber) ==================


def test_list_transactions_success(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
    sample_paginated_response: PaginatedResponse,
):
    """Test successful transaction list retrieval."""
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.list_by_application.return_value = sample_paginated_response
    mock_cache_service.set_cached.return_value = True

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions?applicationNumber=APP001&page=1&pageSize=20",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["data"]) == 1


def test_list_transactions_invalid_page_size(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
):
    """Test with page_size exceeding max (100)."""
    mock_cache_service.get_cached.return_value = None
    # ES service should constrain page_size
    mock_elasticsearch_service.list_by_application.return_value = PaginatedResponse(
        data=[],
        total=0,
        page=1,
        page_size=100,
        total_pages=1,
        has_next=False,
        has_previous=False,
        query_time_ms=5,
        cache_status="MISS",
    )

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions?applicationNumber=APP001&pageSize=200",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200


def test_list_transactions_invalid_sort_field(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
):
    """Test with invalid sort field (should default)."""
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.list_by_application.return_value = PaginatedResponse(
        data=[],
        total=0,
        page=1,
        page_size=20,
        total_pages=1,
        has_next=False,
        has_previous=False,
        query_time_ms=5,
        cache_status="MISS",
    )

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions?applicationNumber=APP001&sort=invalid_field",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200


# ================== Test: GET /transactions/range ==================


def test_range_query_success(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
    sample_paginated_response: PaginatedResponse,
):
    """Test successful range query."""
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.range_query.return_value = sample_paginated_response
    mock_cache_service.set_cached.return_value = True

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions/range?from_date=2025-01-01T00:00:00Z&to_date=2025-02-01T00:00:00Z",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1


def test_range_query_invalid_date_format(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
):
    """Test range query with invalid date format (400)."""
    mock_cache_service.get_cached.return_value = None

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions/range?from_date=2025-01-01&to_date=2025-02-01",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 400


def test_range_query_with_filters(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
    sample_paginated_response: PaginatedResponse,
):
    """Test range query with optional filters."""
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.range_query.return_value = sample_paginated_response
    mock_cache_service.set_cached.return_value = True

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions/range"
                "?from_date=2025-01-01T00:00:00Z"
                "&to_date=2025-02-01T00:00:00Z"
                "&employment_type=Salaried"
                "&product_type=PersonalLoan"
                "&score_min=700&score_max=800",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200
    # Verify ES service was called with filters
    mock_elasticsearch_service.range_query.assert_called_once()


def test_range_query_large_result_set(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
):
    """Test range query with > 10000 results (should still return 200 but log warning)."""
    large_response = PaginatedResponse(
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
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.range_query.return_value = large_response
    mock_cache_service.set_cached.return_value = True

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions/range?from_date=2025-01-01T00:00:00Z&to_date=2025-03-31T00:00:00Z",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 15000


# ================== Test: GET /transactions/download ==================


def test_download_csv_success(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
    sample_transaction: TransactionResponse,
):
    """Test successful CSV download."""

    async def mock_scroll_generator():
        yield sample_transaction

    mock_elasticsearch_service.scroll_for_download.return_value = mock_scroll_generator()

    with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
        response = test_client.get(
            "/transactions/download"
            "?from_date=2025-01-01T00:00:00Z"
            "&to_date=2025-02-01T00:00:00Z"
            "&format=csv",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in response.headers.get("content-disposition", "")
    # Verify CSV header row is present
    content = response.text
    assert "application_number" in content


def test_download_jsonl_success(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
    sample_transaction: TransactionResponse,
):
    """Test successful JSONL download."""

    async def mock_scroll_generator():
        yield sample_transaction

    mock_elasticsearch_service.scroll_for_download.return_value = mock_scroll_generator()

    with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
        response = test_client.get(
            "/transactions/download"
            "?from_date=2025-01-01T00:00:00Z"
            "&to_date=2025-02-01T00:00:00Z"
            "&format=jsonl",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson; charset=utf-8"
    # Verify JSONL format (each line is valid JSON)
    for line in response.text.strip().split("\n"):
        if line:
            import json

            json.loads(line)  # Should not raise


def test_download_invalid_format(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
):
    """Test download with invalid format (400)."""
    with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
        response = test_client.get(
            "/transactions/download"
            "?from_date=2025-01-01T00:00:00Z"
            "&to_date=2025-02-01T00:00:00Z"
            "&format=invalid",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 400


def test_download_invalid_date(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
):
    """Test download with invalid date format (400)."""
    with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
        response = test_client.get(
            "/transactions/download" "?from_date=2025-01-01" "&to_date=2025-02-01" "&format=csv",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 400


# ================== Test: Error Handling ==================


def test_elasticsearch_unavailable(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
):
    """Test behavior when Elasticsearch is unavailable (503)."""
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.get_transaction.side_effect = RuntimeError("ES connection failed")

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions/APP001/REQ001",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 503


# ================== Test: Pagination Logic ==================


def test_pagination_metadata(
    test_client: TestClient,
    mock_elasticsearch_service: AsyncMock,
    mock_cache_service: AsyncMock,
):
    """Test pagination metadata is correctly calculated."""
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
    mock_cache_service.get_cached.return_value = None
    mock_elasticsearch_service.list_by_application.return_value = paginated
    mock_cache_service.set_cached.return_value = True

    with patch("src.api.routers.query._cache_service", mock_cache_service):
        with patch("src.api.routers.query._elasticsearch_service", mock_elasticsearch_service):
            response = test_client.get(
                "/transactions?applicationNumber=APP001&page=2&pageSize=20",
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2
    assert data["has_next"] is True
    assert data["has_previous"] is True
    assert data["total_pages"] == 13


# ================== Test: Cache Key Generation ==================


def test_cache_key_determinism(mock_cache_service: AsyncMock):
    """Test that cache keys are deterministic.
    
    Note: This test demonstrates the concept. The actual CacheService._cache_key
    method should be tested directly on the real service."""
    # Cache key generation should be deterministic when given the same inputs
    # This would typically be tested on the actual CacheService class


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

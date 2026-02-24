"""Unit tests for ElasticsearchService."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from elasticsearch.exceptions import NotFoundError

from src.api.core.config import get_settings
from src.api.services.elasticsearch_service import ElasticsearchService


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def es_service(settings):
    service = ElasticsearchService(settings)
    service.client = MagicMock()
    return service


@pytest.fixture
def disconnected_es_service(settings):
    service = ElasticsearchService(settings)
    service.client = None
    return service


def _make_hit(overrides: dict | None = None) -> dict:
    """Build a minimal Elasticsearch hit _source."""
    base = {
        "application_number": "APP-001",
        "request_id": "REQ-001",
        "transunion_score": 720,
        "loan_amount": "50000.0",
        "tenure_months": 60,
        "interest_rate_apr": "8.5",
        "employment_type": "SALARIED",
        "product_type": "PERSONALLOAN",
        "customer_city": "New York",
        "income_monthly": "5000.0",
        "existing_debt": None,
        "ingested_at": "2024-01-01T00:00:00",
        "schema_version": "1.0",
        "source": "credit-api",
    }
    if overrides:
        base.update(overrides)
    return {"_source": base, "_id": "APP-001:REQ-001"}


@pytest.mark.asyncio
async def test_es_connect():
    """Test that connect initialises client and calls info."""
    settings = get_settings()
    service = ElasticsearchService(settings)
    with patch("src.api.services.elasticsearch_service.Elasticsearch") as mock_es_class:
        mock_client = MagicMock()
        mock_client.info.return_value = {"cluster_name": "test", "version": {"number": "8.0"}}
        mock_es_class.return_value = mock_client
        await service.connect()
        assert service.client is not None
        mock_client.info.assert_called_once()


@pytest.mark.asyncio
async def test_es_connect_failure():
    """Failures in connect() are propagated."""
    settings = get_settings()
    service = ElasticsearchService(settings)
    with patch("src.api.services.elasticsearch_service.Elasticsearch") as mock_es_class:
        mock_es_class.side_effect = Exception("Cannot connect")
        with pytest.raises(Exception, match="Cannot connect"):
            await service.connect()


@pytest.mark.asyncio
async def test_es_disconnect(es_service):
    """Disconnect calls close() on the client."""
    await es_service.disconnect()
    es_service.client.close.assert_called_once()


@pytest.mark.asyncio
async def test_es_disconnect_no_client(disconnected_es_service):
    """Disconnect does nothing when no client."""
    await disconnected_es_service.disconnect()  # Should not raise


@pytest.mark.asyncio
async def test_es_get_transaction_success(es_service):
    """get_transaction returns a TransactionResponse on success."""
    hit = _make_hit()
    es_service.client.get.return_value = hit
    result = await es_service.get_transaction("APP-001", "REQ-001")
    assert result is not None
    assert result.application_number == "APP-001"


@pytest.mark.asyncio
async def test_es_get_transaction_not_found(es_service):
    """get_transaction returns None when document is not in ES."""
    es_service.client.get.side_effect = NotFoundError(
        404, {"error": {"reason": "no such index"}}, {"error": {}}
    )
    result = await es_service.get_transaction("APP-001", "REQ-MISSING")
    assert result is None


@pytest.mark.asyncio
async def test_es_get_transaction_no_client(disconnected_es_service):
    """RuntimeError when client not initialised."""
    with pytest.raises(RuntimeError, match="Elasticsearch not initialized"):
        await disconnected_es_service.get_transaction("APP-001", "REQ-001")


@pytest.mark.asyncio
async def test_es_get_transaction_es_error(es_service):
    """Other Elasticsearch errors are re-raised."""
    es_service.client.get.side_effect = Exception("Internal ES error")
    with pytest.raises(Exception, match="Internal ES error"):
        await es_service.get_transaction("APP-001", "REQ-001")


@pytest.mark.asyncio
async def test_es_list_by_application_success(es_service):
    """list_by_application returns paginated results."""
    hit = _make_hit()
    es_service.client.search.return_value = {
        "hits": {"total": {"value": 1}, "hits": [hit]},
        "took": 5,
    }
    result = await es_service.list_by_application("APP-001", page=1, page_size=10)
    assert result.total == 1
    assert len(result.data) == 1


@pytest.mark.asyncio
async def test_es_list_by_application_no_client(disconnected_es_service):
    with pytest.raises(RuntimeError, match="Elasticsearch not initialized"):
        await disconnected_es_service.list_by_application("APP-001")


@pytest.mark.asyncio
async def test_es_list_by_application_empty(es_service):
    """list_by_application with zero results returns empty page."""
    es_service.client.search.return_value = {
        "hits": {"total": {"value": 0}, "hits": []},
        "took": 2,
    }
    result = await es_service.list_by_application("APP-999")
    assert result.total == 0
    assert result.data == []


@pytest.mark.asyncio
async def test_es_list_by_application_es_error(es_service):
    es_service.client.search.side_effect = Exception("ES search failed")
    with pytest.raises(Exception, match="ES search failed"):
        await es_service.list_by_application("APP-001")


@pytest.mark.asyncio
async def test_es_range_query_success(es_service):
    """range_query returns results between dates."""
    hit = _make_hit()
    es_service.client.search.return_value = {
        "hits": {"total": {"value": 1}, "hits": [hit]},
        "took": 3,
    }
    from_dt = datetime(2024, 1, 1, tzinfo=UTC)
    to_dt = datetime(2024, 1, 31, tzinfo=UTC)
    result = await es_service.range_query(from_dt, to_dt)
    assert result.total == 1


@pytest.mark.asyncio
async def test_es_range_query_exceeds_90_days(es_service):
    """range_query raises ValueError when date range > 90 days."""
    from_dt = datetime(2024, 1, 1, tzinfo=UTC)
    to_dt = datetime(2024, 6, 1, tzinfo=UTC)  # > 90 days
    with pytest.raises(ValueError, match="90 days"):
        await es_service.range_query(from_dt, to_dt)


@pytest.mark.asyncio
async def test_es_range_query_negative_range(es_service):
    """range_query raises ValueError when from_date is after to_date."""
    from_dt = datetime(2024, 2, 1, tzinfo=UTC)
    to_dt = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="before to_date"):
        await es_service.range_query(from_dt, to_dt)


@pytest.mark.asyncio
async def test_es_range_query_no_client(disconnected_es_service):
    from_dt = datetime(2024, 1, 1, tzinfo=UTC)
    to_dt = datetime(2024, 1, 31, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="Elasticsearch not initialized"):
        await disconnected_es_service.range_query(from_dt, to_dt)


@pytest.mark.asyncio
async def test_es_range_query_with_filters(es_service):
    """range_query applies employment_type, product_type filters correctly."""
    hit = _make_hit()
    es_service.client.search.return_value = {
        "hits": {"total": {"value": 1}, "hits": [hit]},
        "took": 2,
    }
    from_dt = datetime(2024, 1, 1, tzinfo=UTC)
    to_dt = datetime(2024, 1, 31, tzinfo=UTC)
    result = await es_service.range_query(
        from_dt, to_dt, filters={"employment_type": "salaried", "score_min": 600}
    )
    assert result.total == 1

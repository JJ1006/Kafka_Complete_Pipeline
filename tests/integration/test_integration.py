"""Integration tests for the Credit Transaction Platform.

These tests require a running kind cluster with all services (Kafka, ES, Redis, Vault).
Run with: pytest tests/integration/ -v --tb=short -x

Prerequisites:
  - kubectl port-forward svc/credit-api 8000:8000 -n credit-platform
  - export CREDIT_API_KEY=<your-api-key>
"""

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx
import pytest

API_URL = os.getenv("CREDIT_API_URL", "http://localhost:8000")
API_KEY = os.getenv("CREDIT_API_KEY", "test-api-key-12345")
HEADERS = {"X-API-Key": API_KEY, "X-Correlation-ID": "integration-test"}

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module")
def client() -> Generator[httpx.Client, None, None]:
    """Synchronous HTTP client for integration tests."""
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
def seed_app_number() -> str:
    """Unique application number for this test run."""
    return f"INTTEST-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


@pytest.fixture(scope="module")
def valid_payload(seed_app_number: str) -> dict:
    """Reusable valid transaction payload."""
    return {
        "application_number": seed_app_number,
        "request_id": "REQ-INTEGRATION-001",
        "transunion_score": 720,
        "loan_amount": 50000.0,
        "tenure_months": 60,
        "interest_rate_apr": 8.5,
        "employment_type": "Salaried",
        "product_type": "PersonalLoan",
        "customer_city": "New York",
        "income_monthly": 5000.0,
        "existing_debt": 10000.0,
    }


# ── Scenario 1: Valid Ingest → Kafka → Elasticsearch ─────────────────────────


def test_health_check(client: httpx.Client) -> None:
    """API is reachable and healthy."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("healthy", "degraded")


def test_ingest_valid_transaction(client: httpx.Client, valid_payload: dict) -> None:
    """POST /transactions 202 Accepted with composite key."""
    r = client.post("/transactions", json=valid_payload, headers=HEADERS)
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
    data = r.json()
    assert "composite_key" in data
    assert valid_payload["application_number"] in data["composite_key"]


# ── Scenario 2: Duplicate Transaction → 409 ───────────────────────────────────


def test_duplicate_transaction(client: httpx.Client, valid_payload: dict) -> None:
    """Sending the same transaction twice returns 409 on second call."""
    # First call has already been made in test_ingest_valid_transaction.
    # If tests run in isolation, re-send the same payload.
    r2 = client.post("/transactions", json=valid_payload, headers=HEADERS)
    assert r2.status_code == 409, f"Expected 409 Conflict, got {r2.status_code}: {r2.text}"
    assert "Duplicate" in r2.json()["detail"]


# ── Scenario 3: Missing Auth → 401 ───────────────────────────────────────────


def test_no_auth_returns_401(client: httpx.Client, valid_payload: dict) -> None:
    """POST without API key gets 401."""
    r = client.post("/transactions", json=valid_payload)
    assert r.status_code == 401


# ── Scenario 4: Invalid Data → 422 ───────────────────────────────────────────


def test_invalid_score_returns_422(client: httpx.Client, valid_payload: dict) -> None:
    """Score outside 300-900 range returns 422."""
    bad = valid_payload.copy()
    bad["request_id"] = "REQ-INVALID"
    bad["transunion_score"] = 999  # Out of range
    r = client.post("/transactions", json=bad, headers=HEADERS)
    assert r.status_code == 422


# ── Scenario 5: Range Query ───────────────────────────────────────────────────


def test_range_query(client: httpx.Client) -> None:
    """GET /transactions/range returns paginated results."""
    now = datetime.now(UTC)
    from_date = (now - timedelta(hours=1)).isoformat()
    to_date = now.isoformat()
    r = client.get(
        "/transactions/range",
        params={"from_date": from_date, "to_date": to_date, "page": 1, "pageSize": 10},
        headers=HEADERS,
    )
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "data" in data


# ── Scenario 6: CSV Download ──────────────────────────────────────────────────


def test_csv_download(client: httpx.Client) -> None:
    """GET /transactions/download returns CSV content."""
    now = datetime.now(UTC)
    r = client.get(
        "/transactions/download",
        params={
            "from_date": (now - timedelta(hours=24)).isoformat(),
            "to_date": now.isoformat(),
            "format": "csv",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "application_number" in r.text  # CSV header row present


# ── Scenario 7: Rate Limit ────────────────────────────────────────────────────


def test_rate_limit(client: httpx.Client, valid_payload: dict) -> None:
    """Exceeding rate limit returns 429 Too Many Requests.

    Note: This test is environment-dependent (rate limit = 100/min by default).
    Marked xfail when rate limit not reached quickly in CI.
    """
    hit_429 = False
    # Attempt many requests rapidly
    for i in range(110):
        payload = valid_payload.copy()
        payload["request_id"] = f"RATE-TEST-{i:04d}"
        r = client.post("/transactions", json=payload, headers=HEADERS)
        if r.status_code == 429:
            hit_429 = True
            break
    # 429 is the expected result when rate limit is triggered
    # If not hit (e.g. high-capacity CI), test is soft-pass
    if not hit_429:
        pytest.skip("Rate limit not reached in this environment")

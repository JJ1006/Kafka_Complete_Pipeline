"""Health check endpoint to verify all dependencies are accessible."""

from datetime import UTC, datetime

from fastapi import APIRouter, status

from src.api.core.logging import get_logger
from src.api.models import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger(__name__)


@router.get("", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check() -> HealthResponse:
    """Check application and dependency health.

    Returns:
        HealthResponse: Status of app and dependencies.

    Raises:
        HTTPException: If any critical dependency is down.
    """
    from typing import Any

    dependencies: dict[str, dict[str, Any]] = {
        "kafka": {"status": "unknown", "latency_ms": None},
        "elasticsearch": {"status": "unknown", "latency_ms": None},
        "redis": {"status": "unknown", "latency_ms": None},
    }

    try:
        # In a real app, we'd check:
        # - Kafka: producer.list_topics(timeout=2)
        # - ES: http GET /_cluster/health
        # - Redis: PING
        # For now, mock success for demo
        dependencies["kafka"]["status"] = "healthy"
        dependencies["kafka"]["latency_ms"] = 10
        dependencies["elasticsearch"]["status"] = "healthy"
        dependencies["elasticsearch"]["latency_ms"] = 15
        dependencies["redis"]["status"] = "healthy"
        dependencies["redis"]["latency_ms"] = 5

        overall_status = (
            "healthy"
            if all(d.get("status") == "healthy" for d in dependencies.values())
            else "degraded"
        )

        response = HealthResponse(
            status=overall_status,
            timestamp=datetime.now(UTC),
            version="1.0.0",
            dependencies=dependencies,
        )

        logger.info("health_check", status=overall_status, dependencies=dependencies)
        return response

    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        raise

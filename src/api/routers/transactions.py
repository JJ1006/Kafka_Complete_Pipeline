"""Ingest router for credit transaction endpoints."""

from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from src.api.core.config import Settings, get_settings
from src.api.core.logging import get_logger
from src.api.models import IngestResponse, TransactionCreate
from src.api.services.dedup_service import RedisDeduplicationService
from src.api.services.kafka_producer import KafkaProducerService

logger = get_logger(__name__)
router = APIRouter(prefix="/transactions", tags=["transactions"])


# Mock implementations for dependency injection (will be initialized in main.py)
_dedup_service: RedisDeduplicationService | None = None
_kafka_producer: KafkaProducerService | None = None


def set_services(
    dedup_service: RedisDeduplicationService, kafka_producer: KafkaProducerService
) -> None:
    """Set service instances for dependency injection.

    Called during application startup in main.py lifespan.
    """
    global _dedup_service, _kafka_producer
    _dedup_service = dedup_service
    _kafka_producer = kafka_producer


async def get_dedup_service() -> RedisDeduplicationService:
    """Get dedup service instance."""
    if _dedup_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Deduplication service unavailable",
        )
    return _dedup_service


async def get_kafka_producer() -> KafkaProducerService:
    """Get Kafka producer instance."""
    if _kafka_producer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kafka producer unavailable",
        )
    return _kafka_producer


async def require_api_key(
    x_api_key: Annotated[str, Header(description="API Key for authentication")] = None,
) -> str:
    """Validate API key from X-API-Key header.

    Args:
        x_api_key: API key from request header.

    Returns:
        Validated API key.

    Raises:
        HTTPException: If API key is missing or invalid.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header required",
            headers={"WWW-Authenticate": "ApiKeyAuth"},
        )

    # In production: validate against Vault/database
    # For now: accept any non-empty key
    if not x_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKeyAuth"},
        )

    return x_api_key


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    summary="Ingest credit transaction",
    description="Accept a credit transaction for processing. Returns 202 Accepted with composite key.",
    responses={
        202: {"description": "Transaction accepted for processing"},
        400: {"description": "Invalid transaction data"},
        401: {"description": "Missing or invalid API key"},
        409: {"description": "Duplicate transaction (dedup check failed)"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "Kafka or Redis unavailable"},
    },
)
async def ingest_transaction(
    request: Request,
    transaction: TransactionCreate,
    api_key: Annotated[str, Depends(require_api_key)],
    dedup_service: Annotated[RedisDeduplicationService, Depends(get_dedup_service)],
    kafka_producer: Annotated[KafkaProducerService, Depends(get_kafka_producer)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_idempotency_key: Annotated[str | None, Header()] = None,
) -> IngestResponse:
    """POST /transactions - Ingest a credit transaction.

    Request headers:
        X-API-Key: Required authentication API key.
        X-Idempotency-Key: Optional idempotency token for safe retries.

    Request body:
        TransactionCreate with applicationNumber, transactionAmount, creditScore, etc.

    Returns:
        202 Accepted with composite_key, ingested_at, correlation_id, trace_id.

    Raises:
        HTTPException: On validation, auth, dedup, or service errors.
    """
    import uuid
    from datetime import datetime

    # Extract request metadata
    request_id = str(uuid.uuid4())
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))

    try:
        logger.info(
            "ingest_transaction_received",
            application_number=transaction.application_number,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # Check idempotency cache (if X-Idempotency-Key provided)
        if x_idempotency_key:
            cached_response = await dedup_service.get_cached_response(x_idempotency_key)
            if cached_response:
                logger.info(
                    "ingest_transaction_cached",
                    idempotency_key=x_idempotency_key,
                    application_number=transaction.application_number,
                )
                return IngestResponse(**cached_response)

        # Deduplication check (atomic SETNX in Redis)
        is_new = await dedup_service.check_and_set(
            transaction.application_number, request_id, ttl_seconds=86400
        )

        if not is_new:
            logger.warning(
                "ingest_transaction_duplicate",
                application_number=transaction.application_number,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate transaction for {transaction.application_number}",
            )

        # Build event data for Kafka
        event_data: dict[str, Any] = {
            "applicationNumber": transaction.application_number,
            "requestId": transaction.request_id,
            "transunionScore": transaction.transunion_score,
            "loanAmount": str(transaction.loan_amount),
            "tenureMonths": transaction.tenure_months,
            "interestRateApr": str(transaction.interest_rate_apr),
            "employmentType": transaction.employment_type,
            "productType": transaction.product_type,
            "customerCity": transaction.customer_city,
            "incomeMonthly": str(transaction.income_monthly)
            if transaction.income_monthly
            else None,
            "existingDebt": str(transaction.existing_debt) if transaction.existing_debt else None,
        }

        # Produce to Kafka
        await kafka_producer.produce_transaction(
            application_number=transaction.application_number,
            request_id=request_id,
            event_data=event_data,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )

        # Build response
        composite_key = f"{transaction.application_number}:{request_id}"
        ingested_at = datetime.now(UTC).isoformat()

        response = IngestResponse(
            composite_key=composite_key,
            ingested_at=ingested_at,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # Cache response for idempotency (if key provided)
        if x_idempotency_key:
            await dedup_service.cache_idempotency_response(
                x_idempotency_key,
                response.model_dump(),
                ttl_seconds=86400,
            )

        logger.info(
            "ingest_transaction_success",
            application_number=transaction.application_number,
            composite_key=composite_key,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "ingest_transaction_error",
            application_number=transaction.application_number,
            error=str(e),
            correlation_id=correlation_id,
            trace_id=trace_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing failed due to service error",
        )

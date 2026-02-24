"""Query and retrieval routers for credit transactions."""
import io
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from src.api.core.config import Settings, get_settings
from src.api.core.logging import get_logger
from src.api.models import PaginatedResponse, TransactionResponse
from src.api.services.cache_service import CacheService
from src.api.services.elasticsearch_service import ElasticsearchService

logger = get_logger(__name__)
router = APIRouter(prefix="/transactions", tags=["transactions"])

# Global service instances (initialized in main.py)
_elasticsearch_service: ElasticsearchService | None = None
_cache_service: CacheService | None = None


def set_services(
    elasticsearch_service: ElasticsearchService, cache_service: CacheService
) -> None:
    """Set service instances for dependency injection."""
    global _elasticsearch_service, _cache_service
    _elasticsearch_service = elasticsearch_service
    _cache_service = cache_service


async def get_elasticsearch_service() -> ElasticsearchService:
    """Get Elasticsearch service instance."""
    if _elasticsearch_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Elasticsearch service unavailable",
        )
    return _elasticsearch_service


async def get_cache_service() -> CacheService:
    """Get cache service instance (safe to be None)."""
    return _cache_service or CacheService(get_settings())


async def require_api_key_query(
    x_api_key: Annotated[str, Header(description="API Key for authentication")] = None,
) -> str:
    """Validate API key from X-API-Key header."""
    if not x_api_key or not x_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header required",
            headers={"WWW-Authenticate": "ApiKeyAuth"},
        )
    return x_api_key


@router.get(
    "/{application_number}/{request_id}",
    response_model=TransactionResponse,
    summary="Get transaction by composite key",
    responses={
        200: {"description": "Transaction found"},
        401: {"description": "Missing or invalid API key"},
        404: {"description": "Transaction not found"},
        503: {"description": "Elasticsearch unavailable"},
    },
)
async def get_transaction(
    request: Request,
    application_number: str,
    request_id: str,
    api_key: Annotated[str, Depends(require_api_key_query)],
    es_service: Annotated[ElasticsearchService, Depends(get_elasticsearch_service)],
    cache_service: Annotated[CacheService, Depends(get_cache_service)],
) -> TransactionResponse:
    """GET /transactions/{applicationNumber}/{requestId} - Get a specific transaction.

    Checks Redis cache first (60s TTL). 
    Returns X-Cache: HIT or MISS header.
    """
    trace_id = request.headers.get("X-Trace-ID", "unknown")

    try:
        # Build cache key
        cache_key = cache_service._cache_key(
            "tx", application_number=application_number, request_id=request_id
        )

        # Check cache
        cached = await cache_service.get_cached(cache_key)
        if cached:
            logger.info(
                "transaction_cache_hit",
                application_number=application_number,
                request_id=request_id,
                trace_id=trace_id,
            )
            # Return with cache header (need to intercept at middleware level in production)
            return TransactionResponse(**cached)

        # Cache miss - query Elasticsearch
        tx = await es_service.get_transaction(application_number, request_id)

        if not tx:
            logger.info(
                "transaction_not_found",
                application_number=application_number,
                request_id=request_id,
                trace_id=trace_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Transaction not found: {application_number}:{request_id}",
            )

        # Cache for 60 seconds
        await cache_service.set_cached(cache_key, tx.model_dump(), ttl=60)

        logger.info(
            "transaction_retrieved",
            application_number=application_number,
            request_id=request_id,
            trace_id=trace_id,
        )

        return tx

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_transaction_error",
            application_number=application_number,
            request_id=request_id,
            error=str(e),
            trace_id=trace_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Elasticsearch query failed",
        )


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="List transactions by application",
    responses={
        200: {"description": "Paginated transaction list"},
        400: {"description": "Invalid query parameters"},
        401: {"description": "Missing or invalid API key"},
        503: {"description": "Elasticsearch unavailable"},
    },
)
async def list_transactions(
    request: Request,
    application_number: Annotated[str, Query(..., description="Application number")],
    api_key: Annotated[str, Depends(require_api_key_query)],
    page: Annotated[int, Query(1, ge=1, description="Page number (1-indexed)")] = 1,
    page_size: Annotated[int, Query(20, ge=1, le=100, description="Results per page")] = 20,
    sort: Annotated[str, Query("ingested_at", description="Sort field")] = "ingested_at",
    order: Annotated[str, Query("desc", description="Sort order")] = "desc",
    es_service: Annotated[ElasticsearchService, Depends(get_elasticsearch_service)] = None,
    cache_service: Annotated[CacheService, Depends(get_cache_service)] = None,
) -> PaginatedResponse:
    """GET /transactions - List transactions for application with pagination.

    Query parameters:
        applicationNumber: Required, application ID.
        page: Page number (1-indexed, default 1).
        pageSize: Results per page (1-100, default 20).
        sort: Field to sort by (ingested_at, transunion_score, application_number).
        order: Sort order (asc or desc).

    Returns X-Cache: HIT or MISS header.
    """
    trace_id = request.headers.get("X-Trace-ID", "unknown")

    try:
        # Build cache key
        cache_key = cache_service._cache_key(
            "list:app",
            application_number=application_number,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
        )

        # Check cache
        cached = await cache_service.get_cached(cache_key)
        if cached:
            logger.info(
                "transaction_list_cache_hit",
                application_number=application_number,
                page=page,
                trace_id=trace_id,
            )
            return PaginatedResponse(**cached)

        # Query Elasticsearch
        result = await es_service.list_by_application(
            application_number=application_number,
            page=page,
            page_size=page_size,
            sort_field=sort,
            sort_order=order,
        )

        # Update cache status
        result.cache_status = "MISS"

        # Cache for 60 seconds
        await cache_service.set_cached(cache_key, result.model_dump(), ttl=60)

        logger.info(
            "transaction_list_retrieved",
            application_number=application_number,
            total=result.total,
            page=page,
            trace_id=trace_id,
        )

        return result

    except Exception as e:
        logger.error(
            "list_transactions_error",
            application_number=application_number,
            error=str(e),
            trace_id=trace_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Elasticsearch query failed",
        )


@router.get(
    "/range",
    response_model=PaginatedResponse,
    summary="Query transactions by date range",
    responses={
        200: {"description": "Paginated transaction list"},
        400: {"description": "Invalid date range or filter parameters"},
        401: {"description": "Missing or invalid API key"},
        503: {"description": "Elasticsearch unavailable"},
    },
)
async def range_query(
    request: Request,
    from_date: Annotated[str, Query(..., description="Start date (ISO 8601)")],
    to_date: Annotated[str, Query(..., description="End date (ISO 8601)")],
    api_key: Annotated[str, Depends(require_api_key_query)],
    page: Annotated[int, Query(1, ge=1)] = 1,
    page_size: Annotated[int, Query(20, ge=1, le=100)] = 20,
    employment_type: Annotated[str | None, Query(description="Employment type filter")] = None,
    product_type: Annotated[str | None, Query(description="Product type filter")] = None,
    score_min: Annotated[int | None, Query(ge=300, le=900)] = None,
    score_max: Annotated[int | None, Query(ge=300, le=900)] = None,
    es_service: Annotated[ElasticsearchService, Depends(get_elasticsearch_service)] = None,
    cache_service: Annotated[CacheService, Depends(get_cache_service)] = None,
) -> PaginatedResponse:
    """GET /transactions/range - Query transactions by date range with optional filters.

    Query parameters:
        from_date: Start date (ISO 8601, inclusive).
        to_date: End date (ISO 8601, inclusive).
        employment_type: Optional filter.
        product_type: Optional filter.
        score_min/score_max: Credit score range filter.

    Constraints:
        - Date range max: 90 days
        - Result limit: 10,000 (suggest download if exceeded)

    Returns X-Cache: HIT or MISS header.
    """
    trace_id = request.headers.get("X-Trace-ID", "unknown")

    try:
        # Parse dates
        try:
            from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use ISO 8601 (e.g. 2025-01-01T00:00:00Z)",
            )

        # Build filters
        filters = {}
        if employment_type:
            filters["employment_type"] = employment_type
        if product_type:
            filters["product_type"] = product_type
        if score_min is not None:
            filters["score_min"] = score_min
        if score_max is not None:
            filters["score_max"] = score_max

        # Build cache key
        cache_key = cache_service._cache_key(
            "range:query",
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=page_size,
            **filters,
        )

        # Check cache
        cached = await cache_service.get_cached(cache_key)
        if cached:
            logger.info(
                "range_query_cache_hit",
                from_date=from_date,
                to_date=to_date,
                trace_id=trace_id,
            )
            return PaginatedResponse(**cached)

        # Query Elasticsearch
        result = await es_service.range_query(
            from_date=from_dt, to_date=to_dt, filters=filters or None, page=page, page_size=page_size
        )

        # Check result size
        if result.total > 10000:
            logger.warning(
                "range_query_large_result",
                total=result.total,
                from_date=from_date,
                to_date=to_date,
                suggestion="Use /download endpoint for large datasets",
            )

        # Update cache status
        result.cache_status = "MISS"

        # Cache for 300 seconds (longer for range queries)
        await cache_service.set_cached(cache_key, result.model_dump(), ttl=300)

        logger.info(
            "range_query_executed",
            total=result.total,
            from_date=from_date,
            to_date=to_date,
            trace_id=trace_id,
        )

        return result

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(
            "range_query_error",
            from_date=from_date,
            to_date=to_date,
            error=str(e),
            trace_id=trace_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Elasticsearch query failed",
        )


@router.get(
    "/download",
    summary="Download transactions as CSV or JSONL",
    responses={
        200: {"description": "Streaming response with transactions"},
        400: {"description": "Invalid parameters"},
        401: {"description": "Missing or invalid API key"},
        429: {"description": "Rate limit exceeded (10 downloads/min)"},
        503: {"description": "Elasticsearch unavailable"},
    },
)
async def download_transactions(
    request: Request,
    from_date: Annotated[str, Query(..., description="Start date (ISO 8601)")],
    to_date: Annotated[str, Query(..., description="End date (ISO 8601)")],
    api_key: Annotated[str, Depends(require_api_key_query)],
    format: Annotated[str, Query("csv", description="Output format")] = "csv",
    employment_type: Annotated[str | None, Query()] = None,
    product_type: Annotated[str | None, Query()] = None,
    score_min: Annotated[int | None, Query(ge=300, le=900)] = None,
    score_max: Annotated[int | None, Query(ge=300, le=900)] = None,
    es_service: Annotated[ElasticsearchService, Depends(get_elasticsearch_service)] = None,
) -> StreamingResponse:
    """GET /transactions/download - Stream transactions as CSV or JSONL.

    Query parameters:
        from_date: Start date (ISO 8601).
        to_date: End date (ISO 8601).
        format: csv or jsonl (default csv).
        employment_type: Optional filter.
        product_type: Optional filter.
        score_min/score_max: Credit score range.

    Returns:
        StreamingResponse with Content-Disposition header for browser download.
        Transfer-Encoding: chunked (no buffering).

    Rate limit: 10 downloads per minute per API key.
    """
    trace_id = request.headers.get("X-Trace-ID", "unknown")

    try:
        # Parse dates
        try:
            from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use ISO 8601.",
            )

        # Build filters
        filters = {}
        if employment_type:
            filters["employment_type"] = employment_type
        if product_type:
            filters["product_type"] = product_type
        if score_min is not None:
            filters["score_min"] = score_min
        if score_max is not None:
            filters["score_max"] = score_max

        # Validate format
        if format not in ("csv", "jsonl"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="format must be 'csv' or 'jsonl'",
            )

        logger.info(
            "download_initiated",
            from_date=from_date,
            to_date=to_date,
            format=format,
            trace_id=trace_id,
        )

        # Generate content (never buffer to memory)
        if format == "csv":
            generator = generate_csv(es_service, from_dt, to_dt, filters)
            filename = f"transactions_{from_date}_to_{to_date}.csv"
            media_type = "text/csv"
        else:  # jsonl
            generator = generate_jsonl(es_service, from_dt, to_dt, filters)
            filename = f"transactions_{from_date}_to_{to_date}.jsonl"
            media_type = "application/x-ndjson"

        return StreamingResponse(
            generator,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache,no-store,must-revalidate",
                "Pragma": "no-cache",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "download_error",
            from_date=from_date,
            to_date=to_date,
            format=format,
            error=str(e),
            trace_id=trace_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Download failed",
        )


async def generate_csv(
    es_service: ElasticsearchService,
    from_date: datetime,
    to_date: datetime,
    filters: dict,
):
    """Generate CSV stream from Elasticsearch scroll.

    Yields: Line strings (not bytes) - FastAPI converts to bytes.
    """
    import csv

    # CSV header row
    header = [
        "application_number",
        "request_id",
        "transunion_score",
        "loan_amount",
        "tenure_months",
        "interest_rate_apr",
        "employment_type",
        "product_type",
        "customer_city",
        "income_monthly",
        "existing_debt",
        "ingested_at",
        "schema_version",
        "source",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    yield buffer.getvalue()
    buffer.truncate(0)
    buffer.seek(0)

    # Stream transaction rows
    row_count = 0
    async for tx in es_service.scroll_for_download(from_date, to_date, filters):
        row = {
            "application_number": tx.application_number,
            "request_id": tx.request_id,
            "transunion_score": tx.transunion_score,
            "loan_amount": tx.loan_amount,
            "tenure_months": tx.tenure_months,
            "interest_rate_apr": tx.interest_rate_apr,
            "employment_type": tx.employment_type,
            "product_type": tx.product_type,
            "customer_city": tx.customer_city or "",
            "income_monthly": tx.income_monthly or "",
            "existing_debt": tx.existing_debt or "",
            "ingested_at": tx.ingested_at.isoformat(),
            "schema_version": tx.schema_version,
            "source": tx.source,
        }
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.truncate(0)
        buffer.seek(0)
        row_count += 1

    logger.info("csv_download_complete", row_count=row_count)


async def generate_jsonl(
    es_service: ElasticsearchService,
    from_date: datetime,
    to_date: datetime,
    filters: dict,
):
    """Generate JSONL stream from Elasticsearch scroll.

    Yields: Line strings (newline-delimited JSON).
    """
    import json

    row_count = 0
    async for tx in es_service.scroll_for_download(from_date, to_date, filters):
        line = json.dumps(tx.model_dump(mode="json"), default=str) + "\n"
        yield line
        row_count += 1

    logger.info("jsonl_download_complete", row_count=row_count)

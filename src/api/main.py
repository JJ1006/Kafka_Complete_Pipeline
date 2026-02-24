"""FastAPI application factory and startup/shutdown management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from src.api.core.config import get_settings
from src.api.core.logging import configure_logging, get_logger
from src.api.models import ErrorResponse
from src.api.routers import health, query, transactions
from src.api.services.cache_service import CacheService
from src.api.services.dedup_service import RedisDeduplicationService
from src.api.services.elasticsearch_service import ElasticsearchService
from src.api.services.kafka_producer import KafkaProducerService

logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager - startup and shutdown.

    Args:
        app: FastAPI application instance.

    Yields:
        None after startup, then cleanup on shutdown.
    """
    # Startup
    logger.info("app_startup", environment=settings.app_env, service="credit-api")
    configure_logging(settings)

    # Initialize services
    dedup_service = RedisDeduplicationService(settings)
    kafka_producer = KafkaProducerService(settings)
    elasticsearch_service = ElasticsearchService(settings)
    cache_service = CacheService(settings)

    try:
        await dedup_service.connect()
        await kafka_producer.connect()
        await elasticsearch_service.connect()
        await cache_service.connect()

        transactions.set_services(dedup_service, kafka_producer)
        query.set_services(elasticsearch_service, cache_service)

        logger.info("all_services_initialized")
    except Exception as e:
        logger.error("service_initialization_failed", error=str(e), exc_info=True)
        raise

    yield

    # Shutdown
    logger.info("app_shutdown", message="Gracefully closing connections")
    await dedup_service.disconnect()
    await kafka_producer.disconnect()
    await elasticsearch_service.disconnect()
    await cache_service.disconnect()


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        FastAPI: Configured application instance.
    """
    app = FastAPI(
        title="Credit Transaction Platform API",
        description="Ingest and query credit transactions with Kafka and Elasticsearch",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS Middleware - allow frontend origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production: specify actual frontend URLs
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Trusted Host Middleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "*.creditplatform.io", "testclient"],
    )

    # GZIP compression for responses > 1KB
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Route registration
    app.include_router(health.router)
    app.include_router(transactions.router)
    app.include_router(query.router)

    # Exception handlers
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle Pydantic validation errors with RFC 7807 format.

        Args:
            request: The request that failed validation.
            exc: The validation error.

        Returns:
            JSONResponse: RFC 7807 error response.
        """
        errors = []
        for error in exc.errors():
            errors.append(
                {"field": ".".join(str(x) for x in error["loc"]), "message": error["msg"]}
            )

        error_response = ErrorResponse(
            type="https://api.creditplatform.io/errors/validation-failed",
            title="Validation Failed",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{len(errors)} validation error(s)",
            instance=str(request.url),
            correlation_id=request.headers.get("X-Correlation-ID", "unknown"),
            trace_id=request.headers.get("X-Trace-ID"),
        )
        logger.warning("validation_error", errors=errors, path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=error_response.model_dump()
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all for unhandled exceptions.

        Args:
            request: The request that caused the error.
            exc: The exception.

        Returns:
            JSONResponse: RFC 7807 error response (never exposes stack trace to client).
        """
        trace_id = request.headers.get("X-Trace-ID", "unknown")
        logger.error("unhandled_exception", error=str(exc), trace_id=trace_id, exc_info=True)

        error_response = ErrorResponse(
            type="https://api.creditplatform.io/errors/internal-server-error",
            title="Internal Server Error",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Check your trace_id with support.",
            instance=str(request.url),
            correlation_id=request.headers.get("X-Correlation-ID", "unknown"),
            trace_id=trace_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_response.model_dump()
        )

    @app.get("/", tags=["root"], include_in_schema=False)
    async def root() -> dict[str, str]:
        """Root endpoint.

        Returns:
            dict: Welcome message with API docs link.
        """
        return {"message": "Credit Transaction Platform API", "docs": "/docs"}

    return app


app = create_app()

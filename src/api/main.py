"""FastAPI application factory and startup/shutdown management."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint

from src.api.core.config import get_settings
from src.api.core.logging import configure_logging, get_logger
from src.api.core.metrics import setup_prometheus_instrumentation
from src.api.core.telemetry import (
    configure_tracing,
    extract_trace_context,
    instrument_fastapi,
    instrument_kafka,
    instrument_redis,
)
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

    # Configure observability (OTel, Prometheus)
    try:
        configure_tracing(settings)
        instrument_fastapi(app)
        instrument_kafka()
        instrument_redis()
        logger.info("observability_configured")
    except Exception as e:
        logger.warning("observability_configuration_failed", error=str(e))

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

    # Prometheus instrumentation (must be after middlewares, before routes)
    try:
        setup_prometheus_instrumentation(app)
    except Exception as e:
        logger.warning("prometheus_instrumentation_failed", error=str(e))

    # Trace context extraction middleware
    @app.middleware("http")
    async def trace_context_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Extract W3C trace context from incoming requests."""
        extract_trace_context(dict(request.headers))
        response = await call_next(request)
        return response

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
        """Root endpoint — redirects browser users to the SPA, returns JSON for API clients."""
        return {"message": "Credit Transaction Platform API", "docs": "/docs", "ui": "/ui"}

    # ── Static files & SPA catch-all ──────────────────────────────────────────
    _spa_dir = os.path.join(os.path.dirname(__file__), "..", "..", "web", "static")
    _spa_index = os.path.join(_spa_dir, "index.html")
    if os.path.isdir(_spa_dir):
        app.mount("/static", StaticFiles(directory=_spa_dir), name="spa-static")
        logger.info("spa_static_files_mounted", directory=_spa_dir)

    @app.get("/ui", include_in_schema=False, response_class=Response)
    @app.get("/ui/{path:path}", include_in_schema=False, response_class=Response)
    async def serve_spa(path: str = "") -> Response:
        """Serve the Vue 3 SPA for all /ui/* routes (client-side routing)."""
        if os.path.isfile(_spa_index):
            return FileResponse(_spa_index, media_type="text/html")
        return JSONResponse(status_code=404, content={"detail": "SPA not built"})

    return app


app = create_app()

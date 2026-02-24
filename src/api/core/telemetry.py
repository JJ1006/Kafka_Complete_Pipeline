"""OpenTelemetry instrumentation and trace propagation configuration."""

from collections.abc import Callable
from functools import wraps
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Optional instrumentors — install packages to enable
try:
    from opentelemetry.instrumentation.kafka import KafkaInstrumentor as _KafkaInstrumentor

    _KAFKA_INSTR = True
except ImportError:
    _KAFKA_INSTR = False

try:
    from opentelemetry.instrumentation.redis import RedisInstrumentor as _RedisInstrumentor

    _REDIS_INSTR = True
except ImportError:
    _REDIS_INSTR = False

try:
    from opentelemetry.propagators.jaeger import JaegerPropagator

    _JAEGER_PROPAGATOR: Any = JaegerPropagator()
except ImportError:
    _JAEGER_PROPAGATOR = None  # type: ignore[assignment]

from src.api.core.config import Settings
from src.api.core.logging import get_logger

logger = get_logger(__name__)


def configure_tracing(settings: Settings) -> None:
    """Configure OpenTelemetry tracing for distributed observability.

    Sets up:
    - OTLPSpanExporter to export traces to gRPC endpoint
    - BatchSpanProcessor for efficient batching
    - W3C TraceContext + Jaeger propagators for cross-service correlation
    - FastAPI, Kafka, and Redis instrumentation
    - Log context enrichment with trace_id

    Args:
        settings: Application settings with OTEL configuration.

    Raises:
        Exception: If OTLP exporter fails to initialize.
    """
    try:
        # Create Resource with service metadata
        resource = Resource.create(
            {
                SERVICE_NAME: settings.otel_service_name,
                SERVICE_VERSION: "1.0.0",
            }
        )

        # Create OTLP Span Exporter (gRPC)
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=True,  # Use insecure for local dev; set False for production
        )

        # Create TracerProvider with batch processor
        trace_provider = TracerProvider(resource=resource)
        trace_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        # Set global tracer provider
        trace.set_tracer_provider(trace_provider)

        # Configure trace propagation (W3C TraceContext + optional Jaeger for compatibility)
        propagators: list[Any] = [TraceContextTextMapPropagator()]
        if _JAEGER_PROPAGATOR is not None:
            propagators.append(_JAEGER_PROPAGATOR)
        set_global_textmap(CompositePropagator(propagators))

        logger.info(
            "otel_tracing_configured",
            endpoint=settings.otel_exporter_otlp_endpoint,
            service=settings.otel_service_name,
        )

    except Exception as e:
        logger.error(
            "otel_tracing_configuration_failed",
            error=str(e),
            exc_info=True,
        )
        raise


def instrument_fastapi(app: Any) -> None:
    """Instrument FastAPI application for automatic span creation.

    Args:
        app: FastAPI application instance.
    """
    try:
        # Instrument FastAPI (excludes health check from tracing noise)
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=["/health", "/docs", "/redoc", "/openapi.json", "/metrics"],
        )
        logger.info("fastapi_instrumentation_enabled")
    except Exception as e:
        logger.error("fastapi_instrumentation_failed", error=str(e), exc_info=True)


def instrument_kafka() -> None:
    """Instrument Kafka producer/consumer for distributed tracing."""
    if not _KAFKA_INSTR:
        logger.debug(
            "kafka_instrumentation_skipped",
            reason="opentelemetry-instrumentation-kafka not installed",
        )
        return
    try:
        _KafkaInstrumentor().instrument()  # type: ignore[name-defined]
        logger.info("kafka_instrumentation_enabled")
    except Exception as e:
        logger.error("kafka_instrumentation_failed", error=str(e), exc_info=True)


def instrument_redis() -> None:
    """Instrument Redis client for distributed tracing."""
    if not _REDIS_INSTR:
        logger.debug(
            "redis_instrumentation_skipped",
            reason="opentelemetry-instrumentation-redis not installed",
        )
        return
    try:
        _RedisInstrumentor().instrument()  # type: ignore[name-defined]
        logger.info("redis_instrumentation_enabled")
    except Exception as e:
        logger.error("redis_instrumentation_failed", error=str(e), exc_info=True)


def get_trace_id() -> str:
    """Extract trace ID from current OpenTelemetry context.

    Returns:
        Trace ID (hex string) or "unknown" if not in active span.
    """
    try:
        span = trace.get_current_span()
        if span and span.is_recording():
            return format(span.get_span_context().trace_id, "032x")
        return "unknown"
    except Exception:
        return "unknown"


def traced_operation(operation_name: str) -> Callable:
    """Decorator for tracing service-layer operations.

    Creates a child span for the decorated function and logs execution details.

    Args:
        operation_name: Human-readable name for the operation.

    Returns:
        Decorated function.

    Example:
        @traced_operation("dedup_check")
        async def check_dedup(app_number: str, req_id: str) -> bool:
            ...
    """

    def decorator(func: Callable) -> Callable:
        tracer = trace.get_tracer(__name__)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(operation_name) as span:
                span.set_attribute("operation.name", operation_name)
                span.set_attribute("operation.async", True)

                trace_id = get_trace_id()
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(trace_id=trace_id)

                try:
                    logger.info(f"{operation_name}_started", trace_id=trace_id)
                    result = await func(*args, **kwargs)
                    logger.info(f"{operation_name}_completed", trace_id=trace_id)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    logger.error(
                        f"{operation_name}_failed",
                        error=str(e),
                        trace_id=trace_id,
                        exc_info=True,
                    )
                    raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(operation_name) as span:
                span.set_attribute("operation.name", operation_name)
                span.set_attribute("operation.async", False)

                trace_id = get_trace_id()
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(trace_id=trace_id)

                try:
                    logger.info(f"{operation_name}_started", trace_id=trace_id)
                    result = func(*args, **kwargs)
                    logger.info(f"{operation_name}_completed", trace_id=trace_id)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    logger.error(
                        f"{operation_name}_failed",
                        error=str(e),
                        trace_id=trace_id,
                        exc_info=True,
                    )
                    raise

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def inject_trace_context(headers: dict[str, Any]) -> dict[str, Any]:
    """Inject W3C trace context into headers for outbound requests.

    Used for propagating trace context to Kafka messages, HTTP requests, etc.

    Args:
        headers: Header dictionary to inject context into.

    Returns:
        Headers with trace context injected.

    Example:
        headers = {"Content-Type": "application/json"}
        headers = inject_trace_context(headers)
        # headers now has traceparent and tracestate
    """
    from opentelemetry.propagate import inject as otel_inject

    return otel_inject(headers)


def extract_trace_context(headers: dict[str, Any]) -> None:
    """Extract and restore W3C trace context from incoming headers.

    Used for propagating trace context from incoming HTTP requests.

    Args:
        headers: Header dictionary to extract context from.

    Example:
        extract_trace_context(request.headers)
        # Current context now includes parent trace information
    """
    from opentelemetry.propagate import extract as otel_extract

    otel_extract(headers)

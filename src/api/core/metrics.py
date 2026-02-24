"""Prometheus metrics and instrumentation for monitoring."""

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import default

from src.api.core.logging import get_logger

logger = get_logger(__name__)


# ================== Custom Metrics ==================


# Kafka Metrics
kafka_produce_total = Counter(
    name="kafka_produce_total",
    documentation="Total Kafka messages produced",
    labelnames=["topic", "status"],  # status: success, failure, timeout
)

kafka_produce_duration_seconds = Histogram(
    name="kafka_produce_duration_seconds",
    documentation="Kafka message production latency in seconds",
    labelnames=["topic"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Redis Cache Metrics
redis_cache_hits_total = Counter(
    name="redis_cache_hits_total",
    documentation="Total Redis cache hits",
    labelnames=["endpoint", "operation"],  # operation: get_tx, list_tx, range_query
)

redis_cache_misses_total = Counter(
    name="redis_cache_misses_total",
    documentation="Total Redis cache misses",
    labelnames=["endpoint", "operation"],
)

redis_cache_hit_rate = Gauge(
    name="redis_cache_hit_rate",
    documentation="Redis cache hit rate (0-1)",
    labelnames=["endpoint"],
)

# Deduplication Metrics
dedup_check_total = Counter(
    name="dedup_check_total",
    documentation="Total deduplication checks",
    labelnames=["result"],  # result: new, duplicate, error
)

dedup_latency_seconds = Histogram(
    name="dedup_latency_seconds",
    documentation="Deduplication check latency in seconds",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

# Elasticsearch Metrics
es_query_duration_seconds = Histogram(
    name="es_query_duration_seconds",
    documentation="Elasticsearch query latency in seconds",
    labelnames=["operation"],  # operation: get, list, range_query, scroll
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

es_query_total = Counter(
    name="es_query_total",
    documentation="Total Elasticsearch queries",
    labelnames=["operation", "status"],  # status: success, failure, not_found
)

# Download Metrics
active_download_streams = Gauge(
    name="active_download_streams",
    documentation="Number of active download streams",
)

download_bytes_total = Counter(
    name="download_bytes_total",
    documentation="Total bytes downloaded",
    labelnames=["format"],  # format: csv, jsonl
)

# Ingest Metrics
ingest_total = Counter(
    name="ingest_total",
    documentation="Total ingest requests",
    labelnames=["status"],  # status: success, duplicate, validation_error, error
)

ingest_latency_seconds = Histogram(
    name="ingest_latency_seconds",
    documentation="Ingest latency in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


# ================== Instrumentation Setup ==================


def setup_prometheus_instrumentation(app: FastAPI) -> Instrumentator:
    """Configure Prometheus instrumentation for FastAPI.

    Includes default metrics (requests, errors, latency) plus custom metrics.

    Args:
        app: FastAPI application instance.

    Returns:
        Configured Instrumentator instance.
    """
    instrumentator = Instrumentator(
        should_group_untemplated=True,  # Group /path/{id} as single metric
        should_ignore_untemplated=True,  # Ignore metrics for paths without templates
    )

    # Add default metrics (request count, error rate, latency, etc.)
    instrumentator.add(default())

    # Instrument the app
    instrumentator.instrument(app).expose(app, should_gzip=True, name="metrics")

    logger.info("prometheus_instrumentation_configured")
    return instrumentator


# ================== Metric Recording Helpers ==================


def record_kafka_produce(topic: str, status: str, duration_seconds: float) -> None:
    """Record Kafka message production metrics.

    Args:
        topic: Kafka topic name.
        status: 'success', 'failure', or 'timeout'.
        duration_seconds: Time taken to produce message.
    """
    kafka_produce_total.labels(topic=topic, status=status).inc()
    if status == "success":
        kafka_produce_duration_seconds.labels(topic=topic).observe(duration_seconds)


def record_cache_access(endpoint: str, operation: str, is_hit: bool) -> None:
    """Record cache access (hit or miss).

    Args:
        endpoint: API endpoint name.
        operation: Operation type (get_tx, list_tx, range_query).
        is_hit: True if cache hit, False if miss.
    """
    if is_hit:
        redis_cache_hits_total.labels(endpoint=endpoint, operation=operation).inc()
    else:
        redis_cache_misses_total.labels(endpoint=endpoint, operation=operation).inc()

    # Update hit rate gauge
    hits = redis_cache_hits_total.labels(endpoint=endpoint, operation=operation)._value.get()
    misses = redis_cache_misses_total.labels(endpoint=endpoint, operation=operation)._value.get()
    total = hits + misses
    if total > 0:
        rate = hits / total
        redis_cache_hit_rate.labels(endpoint=endpoint).set(rate)


def record_dedup_check(result: str, duration_seconds: float) -> None:
    """Record deduplication check metrics.

    Args:
        result: 'new', 'duplicate', or 'error'.
        duration_seconds: Time taken to perform check.
    """
    dedup_check_total.labels(result=result).inc()
    dedup_latency_seconds.observe(duration_seconds)


def record_es_query(operation: str, status: str, duration_seconds: float) -> None:
    """Record Elasticsearch query metrics.

    Args:
        operation: 'get', 'list', 'range_query', or 'scroll'.
        status: 'success', 'failure', or 'not_found'.
        duration_seconds: Query execution time.
    """
    es_query_total.labels(operation=operation, status=status).inc()
    if status == "success":
        es_query_duration_seconds.labels(operation=operation).observe(duration_seconds)


def record_active_download(delta: int) -> None:
    """Update active download streams gauge.

    Args:
        delta: Change in active streams (+1 for new, -1 for completed).
    """
    current = active_download_streams._value.get()
    active_download_streams.set(max(0, current + delta))


def record_download_bytes(format_type: str, byte_count: int) -> None:
    """Record downloaded bytes.

    Args:
        format_type: 'csv' or 'jsonl'.
        byte_count: Number of bytes downloaded.
    """
    download_bytes_total.labels(format=format_type).inc(byte_count)


def record_ingest(status: str, duration_seconds: float) -> None:
    """Record ingest request metrics.

    Args:
        status: 'success', 'duplicate', 'validation_error', or 'error'.
        duration_seconds: Time taken to process request.
    """
    ingest_total.labels(status=status).inc()
    ingest_latency_seconds.observe(duration_seconds)

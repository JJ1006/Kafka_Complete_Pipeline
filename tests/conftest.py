"""Root conftest.py – shared fixtures and environment setup for all tests.

Sets bare-minimum environment variables so imports like ``src.api.main``
succeed in CI (where Kafka / Redis / Elasticsearch are not running).
Service connections are never opened here; tests that need live services
use their own fixtures with mocked clients.
"""

import os

# ── Environment ───────────────────────────────────────────────────────────────
# These defaults mirror the ones already baked into Settings, but setting them
# explicitly ensures get_settings() returns clean, deterministic values even
# when tests are collected on a machine with a .env that overrides defaults.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("APP_API_KEY", "test-api-key-12345")

os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
os.environ.setdefault("KAFKA_SCHEMA_REGISTRY_URL", "http://localhost:8081")
os.environ.setdefault("KAFKA_TOPIC_TRANSACTIONS", "credit.transactions.v1")
os.environ.setdefault("KAFKA_TOPIC_DLQ", "credit.transactions.dlq.v1")

os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("ELASTICSEARCH_INDEX_ALIAS_WRITE", "credit-transactions-write")
os.environ.setdefault("ELASTICSEARCH_INDEX_ALIAS_READ", "credit-transactions-read")

os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("CACHE_TTL_SECONDS", "60")

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
os.environ.setdefault("OTEL_SERVICE_NAME", "credit-api-test")

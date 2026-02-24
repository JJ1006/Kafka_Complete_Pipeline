"""Application configuration using Pydantic Settings v2."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_secret_key: str = Field(default="dev-secret-key-change-in-prod", alias="APP_SECRET_KEY")
    app_api_key: str = Field(default="dev-api-key-change-in-prod", alias="APP_API_KEY")

    # Kafka
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_schema_registry_url: str = Field(
        default="http://localhost:8081", alias="KAFKA_SCHEMA_REGISTRY_URL"
    )
    kafka_topic_transactions: str = Field(
        default="credit.transactions.v1", alias="KAFKA_TOPIC_TRANSACTIONS"
    )
    kafka_topic_dlq: str = Field(default="credit.transactions.dlq.v1", alias="KAFKA_TOPIC_DLQ")

    # Elasticsearch
    elasticsearch_url: str = Field(default="http://localhost:9200", alias="ELASTICSEARCH_URL")
    elasticsearch_index_alias_write: str = Field(
        default="credit-transactions-write", alias="ELASTICSEARCH_INDEX_ALIAS_WRITE"
    )
    elasticsearch_index_alias_read: str = Field(
        default="credit-transactions-read", alias="ELASTICSEARCH_INDEX_ALIAS_READ"
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    cache_ttl_seconds: int = Field(default=60, alias="CACHE_TTL_SECONDS")

    # Auth
    jwt_secret_key: str = Field(default="dev-jwt-secret-key", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=15, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_name: str = Field(default="credit-api", alias="OTEL_SERVICE_NAME")

    # Rate Limits
    rate_limit_ingest: str = Field(default="500/minute", alias="RATE_LIMIT_INGEST")
    rate_limit_query: str = Field(default="1000/minute", alias="RATE_LIMIT_QUERY")
    rate_limit_download: str = Field(default="10/minute", alias="RATE_LIMIT_DOWNLOAD")

    # Limits
    range_max_days: int = Field(default=90, alias="RANGE_MAX_DAYS")
    stream_chunk_size: int = Field(default=1000, alias="STREAM_CHUNK_SIZE")

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: Configured application settings.
    """
    return Settings()

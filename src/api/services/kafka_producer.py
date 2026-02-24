"""Async Kafka producer service for credit transactions using Avro serialization."""

import json
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaProducer
from fastavro import schemaless_writer

from src.api.core.config import Settings
from src.api.core.logging import get_logger

logger = get_logger(__name__)


class KafkaProducerService:
    """Produces credit transaction events to Kafka in Avro format."""

    def __init__(self, settings: Settings):
        """Initialize Kafka producer service.

        Args:
            settings: Application settings with Kafka configuration.
        """
        self.settings = settings
        self.producer: AIOKafkaProducer | None = None
        self.avro_schema: dict[str, Any] | None = None

    async def connect(self) -> None:
        """Initialize Kafka producer and fetch Avro schema from Registry.

        Raises:
            Exception: If Kafka broker or Schema Registry is unreachable.
        """
        try:
            # Initialize producer with idempotence enabled
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.settings.kafka_bootstrap_servers,
                acks="all",  # Wait for all in-sync replicas
                compression_type="snappy",
                linger_ms=5,
                batch_size=65536,
                enable_idempotence=True,
                max_in_flight_requests_per_connection=5,
                retries=2147483647,
                delivery_timeout_ms=120000,
            )
            await self.producer.start()

            # Fetch schema from Schema Registry
            await self._fetch_schema()

            logger.info(
                "kafka_producer_connected",
                bootstrap_servers=self.settings.kafka_bootstrap_servers,
                topic=self.settings.kafka_topic_transactions,
            )
        except Exception as e:
            logger.error("kafka_producer_connection_failed", error=str(e), exc_info=True)
            raise

    async def disconnect(self) -> None:
        """Gracefully shutdown Kafka producer."""
        if self.producer:
            await self.producer.stop()
            logger.info("kafka_producer_disconnected")

    async def _fetch_schema(self) -> None:
        """Fetch Avro schema from Schema Registry and cache it."""
        import aiohttp

        subject = f"{self.settings.kafka_topic_transactions}-value"
        url = f"{self.settings.kafka_schema_registry_url}/subjects/{subject}/versions/latest"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        schema_str = data.get("schema")
                        if schema_str:
                            self.avro_schema = json.loads(schema_str)
                            logger.info("avro_schema_fetched", subject=subject)
                    else:
                        logger.error(
                            "schema_registry_error",
                            subject=subject,
                            status=resp.status,
                        )
        except Exception as e:
            logger.error("schema_registry_fetch_error", error=str(e), exc_info=True)
            raise

    async def produce_transaction(
        self,
        application_number: str,
        request_id: str,
        event_data: dict[str, Any],
        trace_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """Produce transaction event to Kafka topic in Avro format.

        Args:
            application_number: Application identifier (used as message key).
            request_id: Request idempotency key.
            event_data: Transaction event data dict.
            trace_id: Optional OTel trace ID for correlation.
            correlation_id: Optional correlation ID.

        Returns:
            Topic partition offset of produced message.

        Raises:
            Exception: If produce fails after retries.
        """
        if not self.producer or not self.avro_schema:
            raise RuntimeError("Kafka producer not initialized or schema not available")

        try:
            # Build Avro record with metadata
            avro_record = {
                "schemaVersion": "1.0",
                "eventId": str(__import__("uuid").uuid4()),
                "ingestedAt": datetime.now(UTC).isoformat(),
                "source": "credit-api",
                "traceId": trace_id,
                "correlationId": correlation_id,
                "applicationNumber": application_number,
                "requestId": request_id,
                **event_data,
            }

            # Serialize to Avro bytes
            avro_bytes = self._serialize_avro(avro_record)

            # Produce to Kafka
            message_key = application_number.encode("utf-8")
            future = await self.producer.send_and_wait(
                self.settings.kafka_topic_transactions,
                value=avro_bytes,
                key=message_key,
                timestamp_ms=int(datetime.now(UTC).timestamp() * 1000),
            )

            logger.info(
                "kafka_message_produced",
                topic=self.settings.kafka_topic_transactions,
                application_number=application_number,
                request_id=request_id,
                partition=future.partition,
                offset=future.offset,
            )

            return str(future.offset)

        except Exception as e:
            logger.error(
                "kafka_produce_error",
                application_number=application_number,
                request_id=request_id,
                error=str(e),
                exc_info=True,
            )
            raise

    def _serialize_avro(self, record: dict[str, Any]) -> bytes:
        """Serialize record to Avro bytes.

        Args:
            record: Record dict matching Avro schema.

        Returns:
            Serialized Avro bytes.
        """
        from io import BytesIO

        output = BytesIO()
        schemaless_writer(output, self.avro_schema, record)
        return output.getvalue()

"""Async Elasticsearch query service for credit transactions."""
from datetime import datetime, timedelta, timezone
from typing import Any

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError, RequestError

from src.api.core.config import Settings
from src.api.core.logging import get_logger
from src.api.models import PaginatedResponse, TransactionResponse

logger = get_logger(__name__)


class ElasticsearchService:
    """Query credit transactions from Elasticsearch."""

    def __init__(self, settings: Settings):
        """Initialize Elasticsearch service.

        Args:
            settings: Application settings with Elasticsearch configuration.
        """
        self.settings = settings
        self.client: Elasticsearch | None = None

    async def connect(self) -> None:
        """Initialize Elasticsearch async client.

        Raises:
            Exception: If Elasticsearch is unreachable.
        """
        try:
            # ElasticSearch async client
            self.client = Elasticsearch(
                hosts=[self.settings.elasticsearch_url],
                verify_certs=False,  # Dev only; use CA in production
                request_timeout=10,
            )

            # Test connectivity
            info = self.client.info()
            logger.info(
                "elasticsearch_connected",
                cluster=info.get("cluster_name"),
                version=info.get("version", {}).get("number"),
            )
        except Exception as e:
            logger.error("elasticsearch_connection_failed", error=str(e), exc_info=True)
            raise

    async def disconnect(self) -> None:
        """Close Elasticsearch connection."""
        if self.client:
            self.client.close()
            logger.info("elasticsearch_disconnected")

    async def get_transaction(
        self, application_number: str, request_id: str
    ) -> TransactionResponse | None:
        """Get a specific transaction by composite key.

        Args:
            application_number: Application identifier.
            request_id: Request ID.

        Returns:
            TransactionResponse or None if not found.
        """
        if not self.client:
            raise RuntimeError("Elasticsearch not initialized")

        try:
            doc_id = f"{application_number}:{request_id}"
            response = self.client.get(
                index=self.settings.elasticsearch_index_alias_read,
                id=doc_id,
            )

            source = response.get("_source", {})

            return TransactionResponse(
                application_number=source.get("application_number"),
                request_id=source.get("request_id"),
                transunion_score=source.get("transunion_score", 0),
                loan_amount=float(source.get("loan_amount", 0)),
                tenure_months=source.get("tenure_months", 0),
                interest_rate_apr=float(source.get("interest_rate_apr", 0)),
                employment_type=source.get("employment_type", ""),
                product_type=source.get("product_type", ""),
                customer_city=source.get("customer_city"),
                income_monthly=float(source.get("income_monthly"))
                if source.get("income_monthly")
                else None,
                existing_debt=float(source.get("existing_debt"))
                if source.get("existing_debt")
                else None,
                ingested_at=datetime.fromisoformat(source.get("ingested_at", "")),
                schema_version=source.get("schema_version", "1.0"),
                source=source.get("source", ""),
            )
        except NotFoundError:
            logger.info(
                "transaction_not_found",
                application_number=application_number,
                request_id=request_id,
            )
            return None
        except Exception as e:
            logger.error(
                "elasticsearch_get_error",
                application_number=application_number,
                request_id=request_id,
                error=str(e),
                exc_info=True,
            )
            raise

    async def list_by_application(
        self,
        application_number: str,
        page: int = 1,
        page_size: int = 20,
        sort_field: str = "ingested_at",
        sort_order: str = "desc",
    ) -> PaginatedResponse:
        """List transactions for an application with pagination.

        Args:
            application_number: Application identifier.
            page: Page number (1-indexed).
            page_size: Results per page (max 100).
            sort_field: Field to sort by (allowed: ingested_at, transunion_score).
            sort_order: Sort order (asc or desc).

        Returns:
            PaginatedResponse with transactions and pagination metadata.
        """
        if not self.client:
            raise RuntimeError("Elasticsearch not initialized")

        # Validate inputs
        page = max(1, page)
        page_size = min(100, max(1, page_size))

        allowed_sort_fields = ["ingested_at", "transunion_score", "application_number"]
        if sort_field not in allowed_sort_fields:
            sort_field = "ingested_at"

        sort_order = "asc" if sort_order.lower() == "asc" else "desc"

        try:
            from_idx = (page - 1) * page_size

            query = {
                "query": {"match": {"application_number": application_number}},
                "sort": [{sort_field: {"order": sort_order}}],
                "from": from_idx,
                "size": page_size,
                "track_total_hits": True,
            }

            response = self.client.search(
                index=self.settings.elasticsearch_index_alias_read,
                body=query,
            )

            total = response.get("hits", {}).get("total", {}).get("value", 0)
            hits = response.get("hits", {}).get("hits", [])

            transactions = []
            for hit in hits:
                source = hit.get("_source", {})
                try:
                    tx = TransactionResponse(
                        application_number=source.get("application_number"),
                        request_id=source.get("request_id"),
                        transunion_score=source.get("transunion_score", 0),
                        loan_amount=float(source.get("loan_amount", 0)),
                        tenure_months=source.get("tenure_months", 0),
                        interest_rate_apr=float(source.get("interest_rate_apr", 0)),
                        employment_type=source.get("employment_type", ""),
                        product_type=source.get("product_type", ""),
                        customer_city=source.get("customer_city"),
                        income_monthly=float(source.get("income_monthly"))
                        if source.get("income_monthly")
                        else None,
                        existing_debt=float(source.get("existing_debt"))
                        if source.get("existing_debt")
                        else None,
                        ingested_at=datetime.fromisoformat(source.get("ingested_at", "")),
                        schema_version=source.get("schema_version", "1.0"),
                        source=source.get("source", ""),
                    )
                    transactions.append(tx)
                except Exception as e:
                    logger.warning(
                        "transaction_parse_error",
                        hit_id=hit.get("_id"),
                        error=str(e),
                    )
                    continue

            total_pages = (total + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1

            return PaginatedResponse(
                data=transactions,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                query_time_ms=response.get("took", 0),
                cache_status="MISS",
            )

        except Exception as e:
            logger.error(
                "elasticsearch_list_error",
                application_number=application_number,
                error=str(e),
                exc_info=True,
            )
            raise

    async def range_query(
        self,
        from_date: datetime,
        to_date: datetime,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedResponse:
        """Query transactions within date range with optional filters.

        Args:
            from_date: Start date (inclusive).
            to_date: End date (inclusive).
            filters: Optional filter dict (employment_type, product_type, score_min, score_max).
            page: Page number (1-indexed).
            page_size: Results per page (max 100).

        Returns:
            PaginatedResponse with matching transactions.

        Raises:
            ValueError: If date range exceeds 90 days or results > 10000.
        """
        if not self.client:
            raise RuntimeError("Elasticsearch not initialized")

        # Validate date range (max 90 days)
        days_diff = (to_date - from_date).days
        if days_diff > 90:
            raise ValueError("Date range cannot exceed 90 days")
        if days_diff < 0:
            raise ValueError("from_date must be before to_date")

        page = max(1, page)
        page_size = min(100, max(1, page_size))

        try:
            # Build query with date range
            query_clauses = [
                {
                    "range": {
                        "ingested_at": {
                            "gte": from_date.isoformat(),
                            "lte": to_date.isoformat(),
                        }
                    }
                }
            ]

            # Add optional filters
            filters = filters or {}
            if "employment_type" in filters:
                query_clauses.append(
                    {"match": {"employment_type": filters["employment_type"].upper()}}
                )
            if "product_type" in filters:
                query_clauses.append({"match": {"product_type": filters["product_type"].upper()}})
            if "score_min" in filters:
                query_clauses.append(
                    {"range": {"transunion_score": {"gte": filters["score_min"]}}}
                )
            if "score_max" in filters:
                query_clauses.append(
                    {"range": {"transunion_score": {"lte": filters["score_max"]}}}
                )

            from_idx = (page - 1) * page_size

            query_body = {
                "query": {"bool": {"must": query_clauses}},
                "sort": [{"ingested_at": {"order": "desc"}}],
                "from": from_idx,
                "size": page_size,
                "track_total_hits": True,
            }

            response = self.client.search(
                index=self.settings.elasticsearch_index_alias_read,
                body=query_body,
            )

            total = response.get("hits", {}).get("total", {}).get("value", 0)

            # Warn if results exceed 10000 (suggest download)
            if total > 10000:
                logger.warning(
                    "range_query_large_result_set",
                    total=total,
                    from_date=from_date.isoformat(),
                    to_date=to_date.isoformat(),
                )

            hits = response.get("hits", {}).get("hits", [])

            transactions = []
            for hit in hits:
                source = hit.get("_source", {})
                try:
                    tx = TransactionResponse(
                        application_number=source.get("application_number"),
                        request_id=source.get("request_id"),
                        transunion_score=source.get("transunion_score", 0),
                        loan_amount=float(source.get("loan_amount", 0)),
                        tenure_months=source.get("tenure_months", 0),
                        interest_rate_apr=float(source.get("interest_rate_apr", 0)),
                        employment_type=source.get("employment_type", ""),
                        product_type=source.get("product_type", ""),
                        customer_city=source.get("customer_city"),
                        income_monthly=float(source.get("income_monthly"))
                        if source.get("income_monthly")
                        else None,
                        existing_debt=float(source.get("existing_debt"))
                        if source.get("existing_debt")
                        else None,
                        ingested_at=datetime.fromisoformat(source.get("ingested_at", "")),
                        schema_version=source.get("schema_version", "1.0"),
                        source=source.get("source", ""),
                    )
                    transactions.append(tx)
                except Exception as e:
                    logger.warning("transaction_parse_error", hit_id=hit.get("_id"), error=str(e))
                    continue

            total_pages = (total + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1

            return PaginatedResponse(
                data=transactions,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                query_time_ms=response.get("took", 0),
                cache_status="MISS",
            )

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                "elasticsearch_range_query_error",
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                error=str(e),
                exc_info=True,
            )
            raise

    async def scroll_for_download(
        self,
        from_date: datetime,
        to_date: datetime,
        filters: dict[str, Any] | None = None,
    ):
        """Generator for streaming large result sets without buffering.

        Yields one transaction at a time using Elasticsearch scroll API.

        Args:
            from_date: Start date (inclusive).
            to_date: End date (inclusive).
            filters: Optional filter dict.

        Yields:
            TransactionResponse objects one at a time.

        Raises:
            ValueError: If date range exceeds 90 days.
        """
        if not self.client:
            raise RuntimeError("Elasticsearch not initialized")

        # Validate date range
        days_diff = (to_date - from_date).days
        if days_diff > 90:
            raise ValueError("Date range cannot exceed 90 days")

        # Build query (same as range_query)
        query_clauses = [
            {
                "range": {
                    "ingested_at": {
                        "gte": from_date.isoformat(),
                        "lte": to_date.isoformat(),
                    }
                }
            }
        ]

        filters = filters or {}
        if "employment_type" in filters:
            query_clauses.append(
                {"match": {"employment_type": filters["employment_type"].upper()}}
            )
        if "product_type" in filters:
            query_clauses.append({"match": {"product_type": filters["product_type"].upper()}})
        if "score_min" in filters:
            query_clauses.append(
                {"range": {"transunion_score": {"gte": filters["score_min"]}}}
            )
        if "score_max" in filters:
            query_clauses.append(
                {"range": {"transunion_score": {"lte": filters["score_max"]}}}
            )

        query_body = {
            "query": {"bool": {"must": query_clauses}},
            "sort": [{"_id": "asc"}],  # Stable cursor for scroll
            "size": 1000,  # Page size for scroll
        }

        try:
            # Initial search with scroll
            response = self.client.search(
                index=self.settings.elasticsearch_index_alias_read,
                scroll="2m",
                body=query_body,
            )

            scroll_id = response.get("_scroll_id")
            total_yielded = 0

            while True:
                hits = response.get("hits", {}).get("hits", [])

                if not hits:
                    break

                for hit in hits:
                    source = hit.get("_source", {})
                    try:
                        tx = TransactionResponse(
                            application_number=source.get("application_number"),
                            request_id=source.get("request_id"),
                            transunion_score=source.get("transunion_score", 0),
                            loan_amount=float(source.get("loan_amount", 0)),
                            tenure_months=source.get("tenure_months", 0),
                            interest_rate_apr=float(source.get("interest_rate_apr", 0)),
                            employment_type=source.get("employment_type", ""),
                            product_type=source.get("product_type", ""),
                            customer_city=source.get("customer_city"),
                            income_monthly=float(source.get("income_monthly"))
                            if source.get("income_monthly")
                            else None,
                            existing_debt=float(source.get("existing_debt"))
                            if source.get("existing_debt")
                            else None,
                            ingested_at=datetime.fromisoformat(source.get("ingested_at", "")),
                            schema_version=source.get("schema_version", "1.0"),
                            source=source.get("source", ""),
                        )
                        yield tx
                        total_yielded += 1
                    except Exception as e:
                        logger.warning(
                            "transaction_parse_error", hit_id=hit.get("_id"), error=str(e)
                        )
                        continue

                # Get next batch
                response = self.client.scroll(scroll_id=scroll_id, scroll="2m")

            logger.info(
                "scroll_download_complete",
                total_yielded=total_yielded,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            )

        except Exception as e:
            logger.error(
                "elasticsearch_scroll_error",
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                error=str(e),
                exc_info=True,
            )
            raise
        finally:
            # Clean up scroll context
            if self.client and scroll_id:
                try:
                    self.client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    pass  # Ignore cleanup errors

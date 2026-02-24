"""Pydantic models for request and response validation."""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TransactionCreate(BaseModel):
    """Request model for creating a credit transaction."""

    application_number: str = Field(
        ..., min_length=1, max_length=100, description="Unique application identifier"
    )
    request_id: str = Field(
        ..., min_length=1, max_length=100, description="Idempotency key (unique per app)"
    )
    transunion_score: int = Field(..., ge=300, le=900, description="Credit score between 300-900")
    loan_amount: float = Field(..., ge=0, description="Loan amount in dollars")
    tenure_months: int = Field(..., ge=1, le=600, description="Loan tenure in months")
    interest_rate_apr: float = Field(
        ..., ge=0.0, le=100.0, description="Annual interest rate percentage"
    )
    employment_type: str = Field(
        ...,
        description="Employment type",
    )
    product_type: str = Field(
        ..., min_length=1, description="Credit product type (e.g., PersonalLoan, AutoLoan)"
    )
    customer_city: str | None = Field(default=None, max_length=100)
    income_monthly: float | None = Field(default=None, ge=0)
    existing_debt: float | None = Field(default=None, ge=0)

    @field_validator("application_number", "request_id")
    @classmethod
    def validate_alphanumeric_with_special(cls, v: str) -> str:
        """Allow alphanumeric, dash, underscore only."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Must contain only alphanumeric characters, dashes, and underscores")
        return v

    @field_validator("employment_type")
    @classmethod
    def validate_employment_type(cls, v: str) -> str:
        """Validate employment type enum."""
        valid_types = {"Salaried", "SelfEmployed", "Student", "Unemployed", "Other"}
        if v not in valid_types:
            raise ValueError(f"Must be one of {valid_types}")
        return v

    @field_validator("loan_amount", mode="before")
    @classmethod
    def validate_loan_precision(cls, v: Any) -> float:
        """Ensure max 2 decimal places."""
        f = float(v)
        if f != round(f, 2):
            raise ValueError("Maximum 2 decimal places allowed")
        return f

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "application_number": "APP001",
                "request_id": "REQ001",
                "transunion_score": 720,
                "loan_amount": 50000.00,
                "tenure_months": 60,
                "interest_rate_apr": 8.5,
                "employment_type": "Salaried",
                "product_type": "PersonalLoan",
                "customer_city": "New York",
                "income_monthly": 5000.00,
                "existing_debt": 10000.00,
            }
        }


class TransactionResponse(BaseModel):
    """Response model when transaction is retrieved."""

    application_number: str
    request_id: str
    transunion_score: int
    loan_amount: float
    tenure_months: int
    interest_rate_apr: float
    employment_type: str
    product_type: str
    customer_city: str | None = None
    income_monthly: float | None = None
    existing_debt: float | None = None
    ingested_at: datetime
    schema_version: str
    source: str


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    data: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    query_time_ms: int
    cache_status: str = "MISS"


class ErrorResponse(BaseModel):
    """RFC 7807 Problem Details response."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    correlation_id: str
    trace_id: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: datetime
    version: str
    dependencies: dict[str, Any]


class IngestResponse(BaseModel):
    """Response for successful transaction ingest (202 Accepted)."""

    composite_key: str
    ingested_at: datetime
    correlation_id: str
    trace_id: str | None = None
    message: str = "Transaction accepted for processing"

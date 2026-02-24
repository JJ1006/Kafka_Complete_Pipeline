"""Structured logging configuration using structlog."""

import logging
import sys
from typing import Any

import structlog

from src.api.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structured logging for production and development.

    Args:
        settings: Application settings with APP_ENV.
    """
    is_production = settings.app_env == "production"

    # Structlog configuration
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
            if is_production
            else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Standard logging configuration
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO if is_production else logging.DEBUG,
    )


def get_logger(name: str) -> Any:
    """Get a structlog logger instance.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Structlog logger instance.
    """
    return structlog.get_logger(name)

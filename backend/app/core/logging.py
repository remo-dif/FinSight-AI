"""Configure structured application logging from environment settings."""

import json
import logging
import sys

from app.core.ai_observability import safe_fields
from app.core.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
                "name": record.name,
                "time": self.formatTime(record),
                **safe_fields(getattr(record, "ai_fields", {})),
            }
        )


class DevelopmentFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "ai_fields"):
            return JsonFormatter().format(record)
        return super().format(record)


def configure_logging() -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if settings.app_env == "production":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            DevelopmentFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    logging.basicConfig(level=level, handlers=[handler], force=True)

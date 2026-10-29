"""Small, content-free AI operation events; no external telemetry dependency."""

import logging
import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

logger = logging.getLogger(__name__)
_request_id: ContextVar[str | None] = ContextVar("ai_request_id", default=None)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_TEXT_FIELDS = {"request_id", "operation", "provider", "model", "outcome", "error_category"}
_NUMBER_FIELDS = {
    "duration_ms",
    "retrieved_count",
    "input_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "status_code",
}


def _safe_correlation(value) -> bool:
    return (
        isinstance(value, str)
        and bool(_IDENTIFIER.fullmatch(value))
        and not value.lower().startswith(("bearer", "basic", "sk-", "eyj"))
    )


def safe_fields(fields: dict) -> dict:
    """Allowlist telemetry, never serialize prompts, records, IDs of users or exceptions."""
    result = {}
    for key, value in fields.items():
        if key in _TEXT_FIELDS and isinstance(value, str) and _IDENTIFIER.fullmatch(value):
            if key != "request_id" or _safe_correlation(value):
                result[key] = value
        elif key in _NUMBER_FIELDS and type(value) in (int, float):
            if 0 <= value <= 2**63 - 1 and math.isfinite(value):
                result[key] = value
        elif key == "fallback" and type(value) is bool:
            result[key] = value
    return result


@contextmanager
def request_correlation(candidate: str | None):
    value = candidate if _safe_correlation(candidate) else str(uuid4())
    token = _request_id.set(value)
    try:
        yield value
    finally:
        _request_id.reset(token)


@contextmanager
def ai_operation(operation: str, **attributes):
    started = perf_counter()
    fields = {**attributes, "operation": operation, "request_id": _request_id.get()}
    try:
        yield fields
    except BaseException as exc:
        names = {cls.__name__ for cls in type(exc).__mro__}
        category = "internal"
        if "OpenAIError" in names:
            category = "provider"
        elif "CircuitOpenError" in names:
            category = "circuit_open"
        elif isinstance(exc, ValueError) or "HTTPException" in names:
            category = "validation"
        fields.update(outcome="error", error_category=category)
        raise
    else:
        fields.setdefault("outcome", "success")
    finally:
        fields["duration_ms"] = round((perf_counter() - started) * 1000, 3)
        logger.info("ai.operation", extra={"ai_fields": safe_fields(fields)})


def capture_usage(fields: dict, response) -> None:
    usage = getattr(response, "usage", None)
    for source, target in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = getattr(usage, source, None)
        if type(value) is int and value >= 0:
            fields[target] = value

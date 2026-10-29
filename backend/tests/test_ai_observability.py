import json
import logging
from types import SimpleNamespace

import pytest

from app.core.logging import JsonFormatter


def test_ai_events_keep_correlation_and_drop_sensitive_fields(caplog):
    from app.core.ai_observability import ai_operation, request_correlation

    with (
        caplog.at_level(logging.INFO),
        request_correlation("synthetic-request-01"),
        ai_operation("rag.retrieve", provider="local", model="synthetic-model") as fields,
    ):
        fields.update(retrieved_count=2, prompt="private document", api_key="secret")
    record = caplog.records[-1]
    event = json.loads(JsonFormatter().format(record))
    assert event["request_id"] == "synthetic-request-01"
    assert event["operation"] == "rag.retrieve"
    assert event["retrieved_count"] == 2
    assert event["duration_ms"] >= 0
    assert event["outcome"] == "success"
    assert "private document" not in json.dumps(event)
    assert "secret" not in json.dumps(event)


def test_errors_are_categorized_without_logging_provider_messages(caplog):
    from app.core.ai_observability import ai_operation

    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError), ai_operation("llm.complete"):
        raise RuntimeError("Bearer secret-token; confidential merchant")
    event = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert event["error_category"] == "internal"
    assert event["outcome"] == "error"
    assert "secret-token" not in json.dumps(event)


def test_provider_usage_is_recorded_only_when_reported():
    from app.core.ai_observability import capture_usage

    fields = {}
    capture_usage(fields, SimpleNamespace())
    assert fields == {}
    capture_usage(
        fields,
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10)
        ),
    )
    assert fields == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    capture_usage(fields, SimpleNamespace(usage=SimpleNamespace(total_tokens=-1)))
    assert fields["total_tokens"] == 10
    assert "cost" not in fields


def test_nested_and_invalid_request_ids_do_not_leak_between_requests(caplog):
    from app.core.ai_observability import ai_operation, request_correlation

    with caplog.at_level(logging.INFO):
        with request_correlation("outer"):
            with request_correlation("inner\nBearer secret"), ai_operation("llm.complete"):
                pass
            with ai_operation("rag.retrieve"):
                pass
        with ai_operation("llm.complete"):
            pass
    events = [json.loads(JsonFormatter().format(record)) for record in caplog.records]
    assert events[0]["request_id"] != "inner\nBearer secret"
    assert events[1]["request_id"] == "outer"
    assert events[2].get("request_id") is None


@pytest.mark.parametrize(
    "candidate",
    [
        "sk-proj-secret",
        "Bearer:secret",
        "eyJ.synthetic.jwt",
        "x" * 129,
        "with space",
        "line\nbreak",
    ],
)
def test_request_id_does_not_accept_credentials_or_unbounded_text(candidate):
    from app.core.ai_observability import request_correlation

    with request_correlation(candidate) as value:
        assert value != candidate
        assert len(value) == 36


def test_extreme_provider_counts_cannot_break_logging():
    from app.core.ai_observability import safe_fields

    assert safe_fields({"total_tokens": 10**500}) == {}

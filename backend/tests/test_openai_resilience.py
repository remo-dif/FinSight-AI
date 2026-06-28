from unittest.mock import patch

import pytest

from app.core.openai_resilience import CircuitBreaker, CircuitOpenError


def test_circuit_breaker_opens_and_allows_probe_after_cooldown() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=10)

    breaker.record_failure()
    breaker.before_call()
    breaker.record_failure()

    with pytest.raises(CircuitOpenError):
        breaker.before_call()

    with patch("app.core.openai_resilience.monotonic", return_value=100):
        breaker._opened_at = 89  # Simulate elapsed cooldown without sleeping.
        breaker.before_call()
        breaker.record_success()
        breaker.before_call()

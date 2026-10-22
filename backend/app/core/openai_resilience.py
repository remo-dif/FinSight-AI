"""Shared OpenAI client policy and a small process-local circuit breaker."""

from threading import Lock
from time import monotonic
from math import isfinite

from openai import AsyncOpenAI, OpenAI

from app.core.config import settings


def validate_embedding_response(response, model: str, count: int, dimensions: int) -> list[list[float]]:
    """One validation policy for indexing and query embeddings."""
    if getattr(response, "model", None) != model:
        raise ValueError("Unexpected embedding model identity")
    ordered = sorted(response.data, key=lambda row: row.index)
    if [row.index for row in ordered] != list(range(count)):
        raise ValueError("Incomplete embedding response")
    vectors = [[float(item) for item in row.embedding] for row in ordered]
    if any(len(v) != dimensions or not all(isfinite(x) for x in v) for v in vectors):
        raise ValueError("Invalid embedding dimensions or values")
    return vectors


class CircuitOpenError(RuntimeError):
    """Raised when calls are suppressed while the provider circuit is open."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int, reset_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = Lock()

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if monotonic() - self._opened_at >= self.reset_seconds:
                # Permit one probe. A failed probe opens the circuit again.
                self._opened_at = None
                self._failures = self.failure_threshold - 1
                return
            raise CircuitOpenError("OpenAI circuit is open")

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = monotonic()


openai_circuit = CircuitBreaker(
    settings.openai_circuit_failure_threshold,
    settings.openai_circuit_reset_seconds,
)


def create_openai_client() -> OpenAI | None:
    if not settings.openai_api_key:
        return None
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def create_async_openai_client() -> AsyncOpenAI | None:
    if not settings.openai_api_key:
        return None
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )

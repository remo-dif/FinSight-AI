"""Evaluation-only provider transports and a durable request journal."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable

import httpx

from evaluation.real_model_contract import Budget, Profile, canonical, digest

EMBEDDINGS = "/v1/embeddings"
COMPLETIONS = "/v1/chat/completions"


class SafetyError(RuntimeError):
    """The current operation cannot safely proceed."""


class Journal:
    def __init__(self, path: Path, identity: dict, budget: Budget, *, resume: bool = False):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.budget = budget
        try:
            self.db.execute("PRAGMA synchronous=FULL")
            with self.transaction():
                self.db.execute("CREATE TABLE IF NOT EXISTS manifest (identity TEXT NOT NULL)")
                self.db.execute(
                    """CREATE TABLE IF NOT EXISTS attempts (
                    unit TEXT, endpoint TEXT, payload TEXT, input_tokens INTEGER, output_tokens INTEGER, cost TEXT,
                    response TEXT, usage INTEGER, seal TEXT, PRIMARY KEY (unit, endpoint))"""
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS observations (unit TEXT PRIMARY KEY, body TEXT, seal TEXT)"
                )
                stored = self.db.execute("SELECT identity FROM manifest").fetchone()
                expected = canonical(
                    {"version": 1, **identity, "budget": budget.model_dump(mode="json")}
                ).decode()
                if stored is None and resume:
                    raise SafetyError("Resume requires the original initialized journal")
                if stored is None:
                    self.db.execute("INSERT INTO manifest VALUES (?)", (expected,))
                elif stored != (expected,):
                    raise SafetyError("Journal identity or inherited budget differs")
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            yield

    def reserve(
        self,
        unit: str,
        endpoint: str,
        payload: str,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
    ):
        with self.transaction():
            row = self.db.execute(
                "SELECT payload, response FROM attempts WHERE unit=? AND endpoint=?",
                (unit, endpoint),
            ).fetchone()
            if row:
                if row[0] != payload or row[1] is None:
                    raise SafetyError("Cannot resend changed or uncertain provider request")
                return json.loads(row[1])
            totals = self.db.execute(
                "SELECT input_tokens + output_tokens, cost FROM attempts"
            ).fetchall()
            if (
                len(totals) + 1 > self.budget.requests
                or sum(item[0] for item in totals) + input_tokens + output_tokens
                > self.budget.tokens
                or sum(Decimal(item[1]) for item in totals) + cost > self.budget.estimated_cost
            ):
                raise SafetyError("Provider budget exhausted before transmission")
            self.db.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                (unit, endpoint, payload, input_tokens, output_tokens, str(cost)),
            )
        return None

    def confirm(self, unit, endpoint, response, usage):
        with self.transaction():
            self.db.execute(
                "UPDATE attempts SET response=?, usage=?, seal=? WHERE unit=? AND endpoint=? AND response IS NULL",
                (canonical(response).decode(), usage, digest(response), unit, endpoint),
            )

    def assert_resumable(self):
        for tokens, usage, response, seal in self.db.execute(
            "SELECT input_tokens + output_tokens, usage, response, seal FROM attempts WHERE response IS NOT NULL"
        ):
            if seal != digest(json.loads(response)) or (usage is not None and usage > tokens):
                raise SafetyError("Provider journal integrity or token bound failed")
        for body, seal in self.db.execute("SELECT body, seal FROM observations"):
            if seal != digest(json.loads(body)):
                raise SafetyError("Observation journal integrity failed")
        if self.db.execute("SELECT 1 FROM attempts WHERE response IS NULL").fetchone():
            raise SafetyError("Uncertain attempt in journal. Reconcile it before any new run.")

    def observe(self, unit, body):
        with self.transaction():
            self.db.execute(
                "INSERT INTO observations VALUES (?, ?, ?)",
                (unit, canonical(body).decode(), digest(body)),
            )


@dataclass
class Phase:
    unit: str
    embedding_input: list[str] | None = None
    prompt: str | None = None


class Boundary:
    def __init__(self, profile: Profile, journal: Journal, credential: str):
        self.profile = profile
        self.journal = journal
        self.credential = credential
        self.phase: Phase | None = None
        self.seen: set[str] = set()
        self.failure: str | None = None

    @contextmanager
    def during(self, phase: Phase):
        self.phase = phase
        self.seen.clear()
        self.failure = None
        try:
            yield
        finally:
            self.phase = None

    def before(self, request, body):
        phase = self.phase
        endpoint = request.url.path
        if (
            phase is None
            or request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != "api.openai.com"
            or request.url.port not in (None, 443)
            or request.url.userinfo
            or request.url.query
            or request.url.fragment
            or request.headers.get("host") not in {"api.openai.com", "api.openai.com:443"}
            or endpoint in self.seen
        ):
            self.failure = "egress_denied"
            raise SafetyError("Provider request destination, method, or phase denied")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise SafetyError("Invalid provider request") from None
        profile = self.profile
        if endpoint == EMBEDDINGS and profile.embedding_backend == "openai":
            allowed = (
                phase.embedding_input is not None
                and payload.get("input") == phase.embedding_input
                and payload.get("model") == profile.embedding_model
                and set(payload) <= {"input", "model", "dimensions", "encoding_format"}
                and payload.get("dimensions") == 1536
            )
            output = 0
            price = profile.embedding_per_million
        elif endpoint == COMPLETIONS:
            messages = payload.get("messages", [])
            allowed = (
                phase.prompt is not None
                and payload.get("model") == profile.model
                and set(payload)
                == {"messages", "model", "temperature", "max_tokens", "response_format"}
                and payload["max_tokens"] == 450
                and payload["temperature"] == 0
                and payload["response_format"] == {"type": "json_object"}
                and len(messages) == 2
                and messages[0].get("role") == "system"
                and messages[1] == {"role": "user", "content": phase.prompt}
            )
            output = 450
            price = profile.input_per_million
        else:
            allowed = False
        if not allowed:
            self.failure = "egress_denied"
            raise SafetyError("Provider payload is outside the approved phase")
        self.seen.add(endpoint)
        # Byte bound plus allowance for provider-added framing. This is a reservation,
        # not a measurement of provider usage or a billing guarantee.
        input_tokens = len(body) + 256
        cost = (input_tokens * price + output * profile.output_per_million) / 1_000_000
        try:
            cached = self.journal.reserve(
                phase.unit, endpoint, digest(payload), input_tokens, output, cost
            )
        except SafetyError:
            self.failure = "reservation_denied"
            raise
        return phase.unit, endpoint, cached

    def after(self, response, content, unit, endpoint):
        status = response.status_code
        if not 200 <= status < 300:
            self.failure = "rate_limited" if status == 429 else "provider_http_error"
            # Error bodies may contain secrets. Keep the pre-send reservation and
            # leave the attempt unresolved, preventing an automatic replay.
            raise SafetyError("Provider returned a non-success HTTP status")
        try:
            decoded = json.loads(content)
            if not isinstance(decoded, dict):
                raise ValueError
            if self.credential and self.credential in canonical(decoded).decode():
                raise ValueError
            usage = decoded.get("usage")
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            if type(tokens) is not int or tokens < 0:
                tokens = None
            envelope = {
                "status": status,
                "body": decoded,
                "request_id": safe_request_id(response.headers.get("x-request-id")),
            }
            self.journal.confirm(unit, endpoint, envelope, tokens)
            reserved = self.journal.db.execute(
                "SELECT input_tokens + output_tokens FROM attempts WHERE unit=? AND endpoint=?",
                (unit, endpoint),
            ).fetchone()[0]
            if tokens is not None and tokens > reserved:
                self.failure = "usage_exceeded_reservation"
                raise SafetyError("Provider usage exceeded the reserved token bound")
        except (ValueError, UnicodeError):
            self.failure = "response_parse_failure"
            raise SafetyError("Provider response could not be safely persisted") from None
        return as_response(envelope)


def safe_request_id(value):
    if value and len(value) <= 100 and value.startswith("req_") and value[4:].isalnum():
        return value
    return None


def as_response(envelope):
    headers = {}
    if envelope["request_id"]:
        headers["x-request-id"] = envelope["request_id"]
    return httpx.Response(envelope["status"], json=envelope["body"], headers=headers)


class SyncTransport(httpx.BaseTransport):
    def __init__(self, boundary: Boundary, send: Callable | None = None):
        self.boundary = boundary
        self.inner = httpx.HTTPTransport(retries=0, trust_env=False) if send is None else None
        self.send = self.inner.handle_request if self.inner else send

    def handle_request(self, request):
        unit, endpoint, cached = self.boundary.before(request, request.read())
        if cached is not None:
            return as_response(cached)
        try:
            response = self.send(request)
            try:
                return self.boundary.after(response, response.read(), unit, endpoint)
            finally:
                response.close()
        except httpx.TransportError:
            self.boundary.failure = "uncertain_delivery"
            raise

    def close(self):
        if self.inner:
            self.inner.close()


class AsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, boundary: Boundary, send: Callable | None = None):
        self.boundary = boundary
        self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False) if send is None else None
        self.send = self.inner.handle_async_request if self.inner else send

    async def handle_async_request(self, request):
        unit, endpoint, cached = self.boundary.before(request, await request.aread())
        if cached is not None:
            return as_response(cached)
        try:
            response = await self.send(request)
            try:
                return self.boundary.after(response, await response.aread(), unit, endpoint)
            finally:
                await response.aclose()
        except httpx.TransportError:
            self.boundary.failure = "uncertain_delivery"
            raise

    async def aclose(self):
        if self.inner:
            await self.inner.aclose()

"""Evaluation-only provider transports and a durable request journal."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

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
                    response TEXT, usage TEXT, seal TEXT, state TEXT NOT NULL, error TEXT,
                    PRIMARY KEY (unit, endpoint))"""
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS observations (unit TEXT PRIMARY KEY, body TEXT, seal TEXT, state TEXT NOT NULL)"
                )
                stored = self.db.execute("SELECT identity FROM manifest").fetchone()
                expected = canonical(
                    {**identity, "version": 2, "budget": budget.model_dump(mode="json")}
                ).decode()
                if stored is None and resume:
                    raise SafetyError("Resume requires the original initialized journal")
                if stored is None:
                    self.db.execute("INSERT INTO manifest VALUES (?)", (expected,))
                elif stored != (expected,):
                    raise SafetyError("Journal version, identity or inherited budget differs")
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
                "SELECT payload, response, state FROM attempts WHERE unit=? AND endpoint=?",
                (unit, endpoint),
            ).fetchone()
            if row:
                if row[0] != payload or row[2] != "confirmed":
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
                "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 'reserved', NULL)",
                (unit, endpoint, payload, input_tokens, output_tokens, str(cost)),
            )
        return None

    def mark_sending(self, unit, endpoint):
        with self.transaction():
            cursor = self.db.execute(
                "UPDATE attempts SET state='uncertain' WHERE unit=? AND endpoint=? AND state='reserved'",
                (unit, endpoint),
            )
            if cursor.rowcount != 1:
                raise SafetyError("Provider attempt lacks a fresh reservation")

    def finish(self, unit, endpoint, response, usage=None, error=None):
        with self.transaction():
            row = self.db.execute(
                "SELECT payload, input_tokens, output_tokens, cost FROM attempts "
                "WHERE unit=? AND endpoint=? AND state='uncertain'",
                (unit, endpoint),
            ).fetchone()
            if row is None:
                raise SafetyError("Provider attempt was not marked for transmission")
            if usage is not None:
                details = response["body"]["usage"]
                parts = (details.get("prompt_tokens"), details.get("completion_tokens"))
                limits = row[1:3]
                if any(
                    key in details and (type(details[key]) is not int or details[key] < 0)
                    for key in ("prompt_tokens", "completion_tokens")
                ):
                    error = "invalid_provider_usage"
                elif usage > sum(limits) or any(
                    part is not None and part > limit
                    for part, limit in zip(parts, limits, strict=True)
                ):
                    error = "usage_exceeded_reservation"
                elif all(part is not None for part in parts) and sum(parts) != usage:
                    error = "invalid_provider_usage"
            state = "rejected" if error else "confirmed"
            seal = digest([unit, endpoint, row, state, error, usage, response])
            self.db.execute(
                "UPDATE attempts SET response=?, usage=?, seal=?, state=?, error=? "
                "WHERE unit=? AND endpoint=?",
                (
                    canonical(response).decode(),
                    str(usage) if usage is not None else None,
                    seal,
                    state,
                    error,
                    unit,
                    endpoint,
                ),
            )
        return error

    def assert_resumable(self, planned=None):
        for (
            unit,
            endpoint,
            payload,
            inputs,
            outputs,
            cost,
            state,
            error,
            usage,
            response,
            seal,
        ) in self.db.execute(
            "SELECT unit, endpoint, payload, input_tokens, output_tokens, cost, state, error, usage, response, seal FROM attempts"
        ):
            if state != "confirmed" or error is not None or not response:
                raise SafetyError("Uncertain or rejected attempt blocks resume")
            if seal != digest(
                [
                    unit,
                    endpoint,
                    (payload, inputs, outputs, cost),
                    state,
                    error,
                    int(usage) if usage is not None else None,
                    json.loads(response),
                ]
            ):
                raise SafetyError("Provider journal integrity failed")
        for unit, body, seal, state in self.db.execute(
            "SELECT unit, body, seal, state FROM observations"
        ):
            record = json.loads(body)
            if seal != digest([state, record]):
                raise SafetyError("Observation journal integrity failed")
            if state not in {"successful", "operational_failure"}:
                raise SafetyError("Incomplete observation blocks resume")
            if planned is not None and (
                unit not in planned
                or unit != unit_key(record)
                or state != observation_state(record["observation"]["error"])
            ):
                raise SafetyError("Observation is outside the plan or has an invalid state")

    def observe(self, unit, body):
        state = observation_state(body["observation"]["error"])
        with self.transaction():
            self.db.execute(
                "INSERT INTO observations VALUES (?, ?, ?, ?)",
                (unit, canonical(body).decode(), digest([state, body]), state),
            )


def unit_key(entry):
    return f"{entry['case']}:{entry['repetition']:02}"


def observation_state(error):
    if error is None:
        return "successful"
    if error == "model_response_parse_failure":
        return "operational_failure"
    return "incomplete"


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
        self.reused = 0

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
        except (TypeError, ValueError, UnicodeError):
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
        if cached is not None:
            self.reused += 1
        return phase.unit, endpoint, cached

    def after(self, response, content, unit, endpoint):
        status = response.status_code
        envelope = {
            "status": status,
            "body": None,
            "request_id": safe_request_id(response.headers.get("x-request-id")),
        }
        error, tokens = None, None
        if not 200 <= status < 300:
            # Error bodies may contain secrets. Persist only sanitized metadata.
            error = "rate_limited" if status == 429 else "provider_http_error"
        else:
            try:
                decoded = json.loads(content)
                if not isinstance(decoded, dict):
                    raise TypeError
                if self.credential and self.credential in canonical(decoded).decode():
                    raise ValueError
                envelope["body"] = decoded
                usage = decoded.get("usage")
                if usage is not None:
                    tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
                    if type(tokens) is not int or tokens < 0:
                        tokens = None
                        error = "invalid_provider_usage"
            except (TypeError, ValueError, UnicodeError):
                error = "response_parse_failure"

        self.failure = self.journal.finish(unit, endpoint, envelope, tokens, error)
        if self.failure:
            raise SafetyError(self.failure)
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
        self.boundary.journal.mark_sending(unit, endpoint)
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
        self.boundary.journal.mark_sending(unit, endpoint)
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

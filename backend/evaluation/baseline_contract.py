"""Strict adapters for the offline retrieval and answer report contracts."""

import json
import math
import re
from hashlib import sha256
from pathlib import Path

from evaluation.answer_metrics import METRICS as ANSWER_METRICS
from evaluation.retrieval_metrics import METRICS as RETRIEVAL_METRICS
from evaluation.retrieval_metrics import score_at_k

TOLERANCE = 1e-12
TYPES = ("retrieval", "answer")
GRADES = {"pass", "fail", "needs_review", "execution_error", "not_applicable"}
API_STATES = {
    None,
    "ok",
    "abstained",
    "insufficient_evidence",
    "provider_error",
    "extractive_preview",
}
VERSIONS = {"baseline_schema_version": 1, "normalization_version": 2, "metric_contract_version": 1}


class ContractError(ValueError):
    def __init__(self, field, category="invalid_input"):
        super().__init__(field)
        self.field = field
        self.category = category


def require(condition, field, category="invalid_input"):
    if not condition:
        raise ContractError(field, category)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ContractError("nonfinite_json_number")


def _finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "nonfinite_json_number")
    return parsed


def parse_json(data):
    try:
        return json.loads(
            data,
            object_pairs_hook=_unique_pairs,
            parse_constant=_invalid_constant,
            parse_float=_finite_float,
        )
    except (json.JSONDecodeError, UnicodeError, TypeError, RecursionError) as exc:
        raise ContractError("malformed_json") from exc


def load_json(path: Path):
    try:
        return parse_json(path.read_bytes())
    except OSError as exc:
        raise ContractError("missing_or_unreadable_file") from exc


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    ).hexdigest()


def seal(body):
    return {**body, "sha256": digest(body)}


def fields(row, *names):
    require(isinstance(row, dict), "object_required")
    for name in names:
        require(name in row, name)
    return {name: row[name] for name in names}


def token(value, path, pattern=r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}"):
    require(type(value) is str and re.fullmatch(pattern, value) is not None, path)
    return value


def hash_value(value, path):
    return token(value, path, r"[a-f0-9]{64}")


def count(value, path):
    require(type(value) is int and value >= 0, path)
    return value


def boolean(value, path):
    require(type(value) is bool, path)
    return value


def numeric(value, path, lower=0, upper=1):
    require(type(value) in {int, float} and lower <= value <= upper and math.isfinite(value), path)
    return value


def metric_map(values, names):
    selected = fields(values, *names)
    require(set(values) == set(names), "metric_names")
    for name, value in selected.items():
        if value is not None:
            numeric(value, name)
    return selected


def verify_summary(actual, expected, path):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), path, "hard_failure")
        for key, value in expected.items():
            verify_summary(actual[key], value, f"{path}.{key}")
    elif type(expected) is float:
        require(abs(numeric(actual, path) - expected) <= TOLERANCE, path, "hard_failure")
    else:
        require(type(actual) is type(expected) and actual == expected, path, "hard_failure")


def verify_authorization(data, status):
    flags = fields(data, "retrieval_called", "generation_called", "passed")
    for name, value in flags.items():
        boolean(value, name)
    require(
        type(status) is int
        and status == 404
        and flags == {"retrieval_called": False, "generation_called": False, "passed": True},
        "authorization_rejection",
        "hard_failure",
    )
    return {"http_status": status, **flags}


def read_span(span):
    require(isinstance(span, list) and len(span) == 2, "span")
    start, end = span
    require(count(start, "span_start") < count(end, "span_end"), "span")
    return start, end


def verify_retrieval_metrics(row, k):
    entries = row["evidence"]
    require(isinstance(entries, list), "evidence_geometry")
    evidence = {}
    for entry in entries:
        exact_fields(entry, "document", "evidence_key", "span")
        document = token(entry["document"], "evidence_document")
        key = document, token(entry["evidence_key"], "evidence_key")
        require(document in row["scope"] and key not in evidence, "evidence_geometry")
        evidence[key] = read_span(entry["span"])
    require(list(evidence) == sorted(evidence), "evidence_order")
    require(bool(evidence) == bool(row["applicable"]), "evidence_applicability", "hard_failure")
    ranking = row.get("diagnostics", {}).get("ranking", [])
    ranked_spans = [(item["document"], tuple(item["span"])) for item in ranking]
    verify_summary(
        row["metrics"], score_at_k(ranked_spans, evidence, k), "retrieval_metric_consistency"
    )


def normalize_ranking(row, identity, documents):
    result = row.get("results")
    require(isinstance(result, list), "ranked_results")
    require(
        count(row.get("retrieved_count"), "retrieved_count")
        == len(result)
        <= identity["retrieval"]["k"],
        "retrieved_count",
    )
    ranking = []
    for rank, item in enumerate(result, 1):
        item = fields(item, "rank", "document", "chunk_index", "chunk_sha256", "span", "score")
        require(count(item["rank"], "rank") == rank, "rank")
        require(
            type(item["document"]) is str and item["document"] in documents,
            "ranked_document",
            "hard_failure",
        )
        count(item["chunk_index"], "chunk_index")
        hash_value(item["chunk_sha256"], "chunk_sha256")
        read_span(item["span"])
        numeric(item["score"], "score", -1, 1)
        ranking.append(item)
    return ranking


def normalize_retrieval(row, identity, expected):
    track = row.get("track")
    require(
        type(track) is str and track in {"retrieval", "conflict", "diagnostic", "authorization"},
        "track",
    )
    require(row.get("status") == "ok", "retrieval_case_status", "hard_failure")
    require(expected is not None, "case_population", "hard_failure")
    require(track == expected["track"], "track", "hard_failure")
    metrics = metric_map(row.get("metrics"), RETRIEVAL_METRICS)
    applicable = list(RETRIEVAL_METRICS) if track in {"retrieval", "conflict"} else []
    require(
        {name for name, value in metrics.items() if value is not None} == set(applicable),
        "retrieval_applicability",
        "hard_failure",
    )
    scope = sorted(expected["scope"])
    normalized = {
        "id": row["id"],
        "track": track,
        "applicable": applicable,
        "metrics": metrics,
        "scope": scope,
        "evidence": expected["evidence"],
    }
    if track == "authorization":
        require("results" not in row, "authorization_results", "hard_failure")
        auth = row.get("authorization")
        status = fields(auth, "http_status")["http_status"]
        normalized["authorization"] = verify_authorization(auth, status)
    else:
        normalized["diagnostics"] = {
            "ranking": normalize_ranking(row, identity, scope),
            "retrieved_count": row["retrieved_count"],
        }
    verify_retrieval_metrics(normalized, identity["retrieval"]["k"])
    return normalized


def normalize_answer(row, identity, expected):
    require(row.get("execution_status") == "executed", "answer_case_execution", "hard_failure")
    require(
        boolean(row.get("contract_passed"), "contract_passed"), "contract_passed", "hard_failure"
    )
    outcome = row.get("outcome")
    require(
        type(outcome) is str
        and outcome in {"answerable", "abstention_required", "authorization_denied"},
        "outcome",
    )
    api_status = fields(row, "api_status")["api_status"]
    require(
        (api_status is None or type(api_status) is str) and api_status in API_STATES, "api_status"
    )
    grade = fields(row.get("grade"), "status", "metrics")
    status = grade["status"]
    require(type(status) is str and status in GRADES, "grade_status")
    scenario = token(row.get("scenario"), "scenario")
    applicable = row.get("applicable_metrics")
    declared = (
        list(ANSWER_METRICS[:-1])
        if outcome == "answerable"
        else ["abstention_correctness"]
        if outcome == "abstention_required" and row["id"] != "Q08"
        else []
    )
    require(
        isinstance(applicable, list)
        and sorted(map(str, applicable)) == sorted(declared)
        and all(type(item) is str for item in applicable),
        "answer_applicability",
        "hard_failure",
    )
    normalized = {
        "id": row["id"],
        "scenario": scenario,
        "outcome": outcome,
        "applicable": sorted(declared),
        "http_status": count(row.get("http_status"), "http_status"),
        "api_status": api_status,
        "grade": status,
    }
    if expected:
        require(outcome == expected["outcome"], "outcome", "hard_failure")
    if outcome == "authorization_denied":
        require(
            scenario == "baseline"
            and api_status is None
            and status == "pass"
            and grade["metrics"] == {}
            and "prompt_hash" not in row,
            "answer_authorization",
            "hard_failure",
        )
        normalized["metrics"] = {}
        normalized["authorization"] = verify_authorization(
            row.get("authorization"), normalized["http_status"]
        )
        return normalized

    expected_grade = row.get("expected_grade")
    require(type(expected_grade) is str and expected_grade in GRADES, "expected_grade")
    require(
        status == expected_grade and normalized["http_status"] == 200,
        "observed_answer_contract",
        "hard_failure",
    )
    if expected:
        require(expected_grade == expected["grade"], "expected_grade", "hard_failure")
    normalized["expected_grade"] = expected_grade
    normalized["metrics"] = metric_map(grade["metrics"], ANSWER_METRICS)
    if scenario == "baseline":
        require(status == "pass", "baseline_grade", "hard_failure")
        nonnull = set(declared) or {"abstention_correctness"}
        require(
            {name for name, value in normalized["metrics"].items() if value is not None} == nonnull,
            "baseline_answer_applicability",
            "hard_failure",
        )
    parsed = fields(row, "parsed_status")["parsed_status"]
    require((parsed is None or type(parsed) is str) and parsed in API_STATES, "parsed_status")
    normalized["parsed_status"] = parsed
    require(
        (api_status == "provider_error") == (status == "execution_error"),
        "provider_error_grade",
        "hard_failure",
    )
    if row["id"] == "Q08":
        draft = fields(row, "conflict_draft", "public_conflict_explanation")
        required_draft = "pass" if scenario == "baseline" else "fail"
        require(
            draft
            == {
                "conflict_draft": required_draft,
                "public_conflict_explanation": "delivered"
                if api_status == "ok"
                else "unobservable",
            },
            "conflict_diagnostics",
            "hard_failure",
        )
        normalized.update(draft)
    warning = fields(row, "draft_warning")["draft_warning"]
    require(
        warning == ("discarded_unexpected_claim" if scenario == "discarded_fabrication" else None),
        "draft_warning",
        "hard_failure",
    )
    normalized["draft_warning"] = warning
    diagnostic = fields(
        row, "prompt_hash", "prompt_chunks", "raw_reference_count", "public_citation_count"
    )
    if diagnostic["prompt_hash"] is not None:
        hash_value(diagnostic["prompt_hash"], "prompt_hash")
    for field in ("prompt_chunks", "raw_reference_count", "public_citation_count"):
        count(diagnostic[field], field)
    require(
        (api_status == "ok") == (diagnostic["public_citation_count"] > 0),
        "public_citation_count",
        "hard_failure",
    )
    parameters = fields(row, "generation_parameters")["generation_parameters"]
    require(
        parameters is None
        if diagnostic["prompt_hash"] is None
        else parameters == identity["generation_parameters"],
        "generation_parameters",
    )
    if parameters is not None:
        numeric(parameters["temperature"], "temperature", 0, 2)
        count(parameters["max_tokens"], "max_tokens")
    normalized["diagnostics"] = diagnostic
    return normalized


def case_key(row):
    return row["id"], row.get("scenario", "")


def summarize(kind, cases):
    if kind == "retrieval":
        groups = {}
        for track in ("retrieval", "conflict"):
            rows = [row for row in cases if row["track"] == track]
            groups[track] = {
                "applicable_cases": len(rows),
                "measured_cases": len(rows),
                "failed_cases": 0,
                "metrics": {
                    name: sum(row["metrics"][name] for row in rows) / len(rows) if rows else None
                    for name in RETRIEVAL_METRICS
                },
            }
        return groups
    rows = [row for row in cases if row["scenario"] == "baseline"]
    metrics = {}
    for name in ANSWER_METRICS:
        values = [row["metrics"][name] for row in rows if name in row["applicable"]]
        metrics[name] = {
            "applicable": len(values),
            "evaluated": len(values),
            "mean": sum(values) / len(values) if values else None,
        }
    return {
        "planned": len(rows),
        "executed": len(rows),
        "pass": len(rows),
        "fail": 0,
        "needs_review": 0,
        "not_applicable": 0,
        "execution_error": 0,
        "skipped": 0,
        "metrics": metrics,
    }


def normalize_report(kind, report, context):
    """Bind an actual report to input digests from the checkout that ran it."""
    require(kind in TYPES and isinstance(report, dict), "evaluation_type")
    require(
        type(report.get("report_version")) is int and report["report_version"] == 1,
        "report_version",
    )
    if kind == "retrieval":
        require(boolean(report.get("complete"), "complete"), "incomplete_execution", "hard_failure")
        require(
            report.get("skips") == [] and report.get("errors") == [],
            "skips_or_errors",
            "hard_failure",
        )
    else:
        execution = fields(
            report.get("execution"), "complete", "planned", "executed", "errors", "skipped"
        )
        require(boolean(execution["complete"], "complete"), "incomplete_execution", "hard_failure")
        for name in ("planned", "executed", "errors", "skipped"):
            count(execution[name], name)
        require(
            execution["errors"] == execution["skipped"] == 0
            and execution["planned"] == execution["executed"],
            "incomplete_execution",
            "hard_failure",
        )
        require(
            boolean(report.get("evaluator_contract_passed"), "evaluator_contract_passed"),
            "evaluator_contract",
            "hard_failure",
        )
        require(
            report.get("model_quality_measured") is False
            and "threshold_result" in report
            and report["threshold_result"] is None,
            "offline_quality_flags",
            "hard_failure",
        )
        require(
            count(
                fields(report.get("generation"), "provider_calls")["provider_calls"],
                "provider_calls",
            )
            == 0,
            "provider_calls",
            "hard_failure",
        )

    identity = fields(
        report,
        "report_version",
        "mode",
        "dataset_schema_version",
        "dataset_version",
        "corpus_version",
        "corpus_hashes",
    )
    require(
        type(identity["dataset_schema_version"]) is int and identity["dataset_schema_version"] == 2,
        "dataset_schema_version",
    )
    require(
        identity["mode"]
        == ("deterministic_local" if kind == "retrieval" else "deterministic_fake"),
        "mode",
    )
    for key in ("dataset_version", "corpus_version"):
        token(identity[key], key, r"[0-9]+\.[0-9]+\.[0-9]+")
    corpus_hashes = identity["corpus_hashes"]
    require(isinstance(corpus_hashes, dict) and bool(corpus_hashes), "corpus_hashes")
    for key, value in corpus_hashes.items():
        token(key, "corpus_key")
        hash_value(value, "corpus_hash")
    require(corpus_hashes == context["corpus_hashes"], "checkout_corpus_mismatch")
    identity["dataset_sha256"] = hash_value(context["dataset_sha256"], "dataset_sha256")
    identity["pgvector_image"] = token(
        context["pgvector_image"], "pgvector_image", r"pgvector/pgvector@sha256:[a-f0-9]{64}"
    )
    identity["renderer"] = token(
        report.get("pdf_renderer" if kind == "retrieval" else "fixture_renderer"), "renderer"
    )
    db = fields(report.get("database"), "backend", "pgvector_version", "hnsw_present")
    require(db["backend"] == "postgresql", "database_backend")
    token(db["pgvector_version"], "pgvector_version")
    boolean(db["hnsw_present"], "hnsw_present")
    identity["database"] = db
    embedding = fields(report.get("embedding"), "model", "dimensions")
    token(embedding["model"], "embedding_model")
    require(count(embedding["dimensions"], "embedding_dimensions") > 0, "embedding_dimensions")
    identity["embedding"] = {"backend": "local", **embedding}
    config = fields(report.get("retrieval"), "k", "min_score")
    require(1 <= count(config["k"], "k") <= 20, "k")
    numeric(config["min_score"], "min_score", -1, 1)
    identity["retrieval"] = config
    if kind == "retrieval":
        require(
            fields(report["database"], "pgvector_used")["pgvector_used"] is True,
            "pgvector_not_used",
            "hard_failure",
        )
        require(fields(report["embedding"], "backend")["backend"] == "local", "embedding_backend")
        chunking = fields(report.get("chunking"), "units", "size", "overlap")
        require(chunking["units"] == "whitespace", "chunk_units")
    else:
        require(
            report.get("dataset_sha256") == identity["dataset_sha256"], "checkout_dataset_mismatch"
        )
        identity["rubric_version"] = token(report.get("rubric_version"), "rubric_version")
        identity["rubric_sha256"] = hash_value(report.get("rubric_sha256"), "rubric_sha256")
        require(identity["rubric_sha256"] == context["rubric_sha256"], "checkout_rubric_mismatch")
        identity["stimulus_sha256"] = hash_value(context["stimulus_sha256"], "stimulus_sha256")
        model = token(report.get("requested_generation_model"), "requested_generation_model")
        rows = report.get("cases")
        require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "cases")
        observed = next(
            (
                row["generation_parameters"]
                for row in rows
                if row.get("generation_parameters") is not None
            ),
            None,
        )
        parameters = fields(observed, "model", "temperature", "max_tokens", "format")
        require(
            parameters["model"] == model and parameters["format"] == "json_object",
            "generation_parameters",
        )
        numeric(parameters["temperature"], "temperature", 0, 2)
        count(parameters["max_tokens"], "max_tokens")
        identity["generation_parameters"] = parameters
        chunking = {
            "units": "whitespace",
            "size": report["retrieval"].get("chunk_size"),
            "overlap": report["retrieval"].get("overlap"),
        }
    require(
        0 <= count(chunking["overlap"], "overlap") < count(chunking["size"], "size"), "chunking"
    )
    identity["chunking"] = chunking

    rows = report.get("cases")
    require(isinstance(rows, list), "cases")
    expected = context["populations"][kind]
    seen = set()
    normalized = []
    for row in rows:
        key = (
            token(fields(row, "id")["id"], "case_id", r"Q[0-9]{2,4}"),
            (token(row.get("scenario"), "scenario") if kind == "answer" else ""),
        )
        require(key not in seen, "duplicate_case")
        seen.add(key)
        adapter = normalize_retrieval if kind == "retrieval" else normalize_answer
        normalized.append(adapter(row, identity, expected.get(key)))
    require(seen == expected.keys(), "case_population", "hard_failure")
    normalized.sort(key=case_key)
    require(
        {row["id"] for row in normalized if "authorization" in row} == {"Q10", "Q11"},
        "authorization_population",
        "hard_failure",
    )
    if kind == "answer":
        require(execution["planned"] == len(normalized), "execution_count", "hard_failure")
        verify_summary(
            report.get("authorization"),
            {"planned": 2, "passed": 2, "contract_passed": True},
            "authorization",
        )
    summary = summarize(kind, normalized)
    verify_summary(
        report.get("aggregates" if kind == "retrieval" else "baseline_aggregate"),
        summary,
        "aggregates",
    )
    source = {
        "git_commit": token(report.get("git_commit"), "git_commit", r"[a-f0-9]{40}"),
        "working_tree_dirty": boolean(report.get("working_tree_dirty"), "working_tree_dirty"),
        "python": token(context["python"], "python"),
        "environment": token(context["environment"], "environment"),
        "dependencies_sha256": hash_value(context["dependencies_sha256"], "dependencies_sha256"),
    }
    return seal(
        {
            **VERSIONS,
            "evaluation_type": kind,
            "identity": identity,
            "source": source,
            "cases": normalized,
            "aggregates": summary,
            "execution": {
                "complete": True,
                "planned": len(normalized),
                "executed": len(normalized),
                "errors": 0,
                "skipped": 0,
            },
        }
    )


def exact_fields(row, *names):
    fields(row, *names)
    require(set(row) == set(names), "unexpected_fields")


def _validate_identity(kind, identity):
    keys = (
        "report_version",
        "mode",
        "dataset_schema_version",
        "dataset_version",
        "dataset_sha256",
        "corpus_version",
        "corpus_hashes",
        "pgvector_image",
        "renderer",
        "database",
        "embedding",
        "retrieval",
        "chunking",
    )
    if kind == "answer":
        keys += ("rubric_version", "rubric_sha256", "stimulus_sha256", "generation_parameters")
    exact_fields(identity, *keys)
    require(
        type(identity["report_version"]) is int and identity["report_version"] == 1,
        "report_version",
    )
    require(
        type(identity["dataset_schema_version"]) is int and identity["dataset_schema_version"] == 2,
        "dataset_schema_version",
    )
    require(
        identity["mode"]
        == ("deterministic_local" if kind == "retrieval" else "deterministic_fake"),
        "mode",
    )
    for key in ("dataset_version", "corpus_version", "renderer"):
        token(identity[key], key)
    hash_value(identity["dataset_sha256"], "dataset_sha256")
    token(identity["pgvector_image"], "pgvector_image", r"pgvector/pgvector@sha256:[a-f0-9]{64}")
    hashes = identity["corpus_hashes"]
    require(isinstance(hashes, dict) and bool(hashes), "corpus_hashes")
    for key, value in hashes.items():
        token(key, "corpus_document")
        hash_value(value, "corpus_hash")
    db = identity["database"]
    exact_fields(db, "backend", "pgvector_version", "hnsw_present")
    require(db["backend"] == "postgresql", "database_backend")
    token(db["pgvector_version"], "pgvector_version")
    boolean(db["hnsw_present"], "hnsw_present")
    embedding = identity["embedding"]
    exact_fields(embedding, "backend", "model", "dimensions")
    require(embedding["backend"] == "local", "embedding_backend")
    token(embedding["model"], "embedding_model")
    require(count(embedding["dimensions"], "dimensions") > 0, "dimensions")
    config = identity["retrieval"]
    exact_fields(config, "k", "min_score")
    require(1 <= count(config["k"], "k") <= 20, "k")
    numeric(config["min_score"], "min_score", -1, 1)
    chunks = identity["chunking"]
    exact_fields(chunks, "units", "size", "overlap")
    require(chunks["units"] == "whitespace", "chunk_units")
    require(count(chunks["overlap"], "overlap") < count(chunks["size"], "chunk_size"), "chunking")
    if kind == "answer":
        token(identity["rubric_version"], "rubric_version")
        hash_value(identity["rubric_sha256"], "rubric_sha256")
        hash_value(identity["stimulus_sha256"], "stimulus_sha256")
        generation = identity["generation_parameters"]
        exact_fields(generation, "model", "temperature", "max_tokens", "format")
        token(generation["model"], "generation_model")
        numeric(generation["temperature"], "temperature", 0, 2)
        count(generation["max_tokens"], "max_tokens")
        require(generation["format"] == "json_object", "generation_format")


def _validate_normalized_case(kind, row, identity):
    fields(row, "id", "metrics", "applicable")
    token(row["id"], "case_id", r"Q[0-9]{2,4}")
    authorization = "authorization" in row
    common = ("id", "metrics", "applicable")
    if kind == "retrieval":
        track = fields(row, "track")["track"]
        require(
            type(track) is str
            and track in {"retrieval", "conflict", "diagnostic", "authorization"},
            "track",
        )
        require((track == "authorization") == authorization, "authorization_track", "hard_failure")
        exact_fields(
            row,
            *common,
            "track",
            "scope",
            "evidence",
            "authorization" if authorization else "diagnostics",
        )
        scope = row["scope"]
        require(isinstance(scope, list) and bool(scope), "document_scope")
        require(
            all(type(doc) is str and doc in identity["corpus_hashes"] for doc in scope),
            "document_scope",
        )
        require(scope == sorted(set(scope)), "document_scope")
        applicable = list(RETRIEVAL_METRICS) if track in {"retrieval", "conflict"} else []
        metrics = metric_map(row["metrics"], RETRIEVAL_METRICS)
        require(
            {name for name, value in metrics.items() if value is not None} == set(applicable),
            "retrieval_applicability",
            "hard_failure",
        )
        if not authorization:
            exact_fields(row["diagnostics"], "ranking", "retrieved_count")
            ranking = row["diagnostics"]["ranking"]
            require(isinstance(ranking, list), "ranking")
            require(
                normalize_ranking(
                    {"results": ranking, "retrieved_count": row["diagnostics"]["retrieved_count"]},
                    identity,
                    scope,
                )
                == ranking,
                "ranking_fields",
            )
        verify_retrieval_metrics(row, identity["retrieval"]["k"])
    else:
        fields(row, "scenario", "outcome", "http_status", "api_status", "grade")
        token(row["scenario"], "scenario")
        outcome = row["outcome"]
        require(
            type(outcome) is str
            and outcome in {"answerable", "abstention_required", "authorization_denied"},
            "outcome",
        )
        require(
            (outcome == "authorization_denied") == authorization,
            "authorization_outcome",
            "hard_failure",
        )
        common += ("scenario", "outcome", "http_status", "api_status", "grade")
        status = row["grade"]
        require(type(status) is str and status in GRADES, "grade")
        api = row["api_status"]
        require((api is None or type(api) is str) and api in API_STATES, "api_status")
        applicable = (
            sorted(ANSWER_METRICS[:-1])
            if outcome == "answerable"
            else ["abstention_correctness"]
            if outcome == "abstention_required" and row["id"] != "Q08"
            else []
        )
        if authorization:
            exact_fields(row, *common, "authorization")
            require(
                row["scenario"] == "baseline"
                and status == "pass"
                and api is None
                and row["http_status"] == 404,
                "authorization_case",
                "hard_failure",
            )
            require(row["metrics"] == {}, "authorization_metrics")
        else:
            extra = ("conflict_draft", "public_conflict_explanation") if row["id"] == "Q08" else ()
            exact_fields(
                row,
                *common,
                "expected_grade",
                "parsed_status",
                "draft_warning",
                "diagnostics",
                *extra,
            )
            require(
                row["http_status"] == 200 and status == row["expected_grade"],
                "answer_case",
                "hard_failure",
            )
            require(
                (api == "provider_error") == (status == "execution_error"),
                "provider_error_grade",
                "hard_failure",
            )
            metrics = metric_map(row["metrics"], ANSWER_METRICS)
            if row["scenario"] == "baseline":
                require(status == "pass", "baseline_grade", "hard_failure")
                require(
                    {name for name, value in metrics.items() if value is not None}
                    == (set(applicable) or {"abstention_correctness"}),
                    "answer_applicability",
                    "hard_failure",
                )
            if extra:
                require(
                    row["conflict_draft"] == ("pass" if row["scenario"] == "baseline" else "fail")
                    and row["public_conflict_explanation"]
                    == ("delivered" if api == "ok" else "unobservable"),
                    "conflict_diagnostics",
                    "hard_failure",
                )
            require(
                row["draft_warning"]
                == (
                    "discarded_unexpected_claim"
                    if row["scenario"] == "discarded_fabrication"
                    else None
                ),
                "draft_warning",
                "hard_failure",
            )
            parsed = row["parsed_status"]
            require(
                (parsed is None or type(parsed) is str) and parsed in API_STATES, "parsed_status"
            )
            diag = row["diagnostics"]
            exact_fields(
                diag, "prompt_hash", "prompt_chunks", "raw_reference_count", "public_citation_count"
            )
            if diag["prompt_hash"] is not None:
                hash_value(diag["prompt_hash"], "prompt_hash")
            for name in ("prompt_chunks", "raw_reference_count", "public_citation_count"):
                count(diag[name], name)
            require(
                (api == "ok") == (diag["public_citation_count"] > 0),
                "public_citation_count",
                "hard_failure",
            )
    require(row["applicable"] == applicable, "applicability", "hard_failure")
    if authorization:
        auth = row["authorization"]
        exact_fields(auth, "http_status", "retrieval_called", "generation_called", "passed")
        verify_authorization(auth, auth["http_status"])


def validate_baseline(value):
    exact_fields(
        value,
        *VERSIONS,
        "evaluation_type",
        "identity",
        "source",
        "cases",
        "aggregates",
        "execution",
        "sha256",
    )
    for key, expected in VERSIONS.items():
        require(type(value[key]) is int and value[key] == expected, key)
    kind = value["evaluation_type"]
    require(kind in TYPES, "evaluation_type")
    body = {key: item for key, item in value.items() if key != "sha256"}
    try:
        calculated = digest(body)
    except (ValueError, TypeError) as exc:
        raise ContractError("baseline_digest") from exc
    require(hash_value(value["sha256"], "baseline_sha256") == calculated, "baseline_digest")
    _validate_identity(kind, value["identity"])
    source = value["source"]
    exact_fields(
        source, "git_commit", "working_tree_dirty", "python", "environment", "dependencies_sha256"
    )
    token(source["git_commit"], "git_commit", r"[a-f0-9]{40}")
    boolean(source["working_tree_dirty"], "working_tree_dirty")
    token(source["python"], "python")
    token(source["environment"], "environment")
    hash_value(source["dependencies_sha256"], "dependencies_sha256")
    rows = value["cases"]
    require(isinstance(rows, list) and rows, "cases")
    for row in rows:
        _validate_normalized_case(kind, row, value["identity"])
    keys = [case_key(row) for row in rows]
    require(len(set(keys)) == len(keys), "duplicate_case")
    verify_summary(
        value["execution"],
        {"complete": True, "planned": len(rows), "executed": len(rows), "errors": 0, "skipped": 0},
        "execution",
    )
    require(
        {row["id"] for row in rows if "authorization" in row} == {"Q10", "Q11"},
        "authorization_population",
        "hard_failure",
    )
    verify_summary(value["aggregates"], summarize(kind, rows), "aggregates")
    return value

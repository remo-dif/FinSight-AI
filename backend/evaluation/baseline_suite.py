"""Run and compare the offline RAG suites against an explicitly trusted Git base."""

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.baseline_contract import (
    TYPES,
    ContractError,
    digest,
    load_json,
    normalize_report,
    parse_json,
    require,
    token,
    validate_baseline,
)
from evaluation.compare_baseline import compare, failure
from evaluation.evidence_mapping import map_evidence
from evaluation.schemas import DATA_DIRECTORY

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_BASE = "5a388bedbc66a1e6283db5ab10baa46ce1489b95"
PGVECTOR_IMAGE = (
    "pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a"
)
RUNNERS = {"retrieval": "evaluation.retrieval_runner", "answer": "evaluation.answer_runner"}
PATHS = {kind: f"backend/evaluation/baselines/{kind}_v1.json" for kind in TYPES}
INPUTS = [
    "backend/evaluation/data/document_qa_v1.json",
    "backend/evaluation/data/document_answer_rubric_v1.json",
    "backend/evaluation/data/corpus",
    "backend/evaluation/answer_runner.py",
]


def git(*args, root=ROOT):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def write_json(path, document):
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def context_for_checkout(*, python=None, environment=None, dependencies_sha256=None):
    # Import the application-backed modules only after CLI configuration is validated.
    from evaluation.answer_rubric import RUBRIC_PATH
    from evaluation.answer_runner import ADVERSARIAL, BASE
    from evaluation.retrieval_runner import track_for
    from evaluation.schemas import load_document_dataset

    bundle = load_document_dataset()
    # verify_pdf requires the extracted text to equal the corpus after whitespace
    # normalization, so the validated source supplies the same token coordinates.
    spans = {
        doc.key: map_evidence(
            (DATA_DIRECTORY / "corpus" / doc.path).read_text(encoding="utf-8"),
            {passage.key: passage.text for passage in doc.evidence},
        )
        for doc in bundle.corpus.documents
    }
    retrieval = {}
    answers = {}
    for case in bundle.dataset.cases:
        references = sorted((ref.document_key, ref.evidence_key) for ref in case.relevant_evidence)
        retrieval[case.id, ""] = {
            "track": track_for(case),
            "scope": case.document_scope,
            "evidence": [
                {"document": doc, "evidence_key": key, "span": list(spans[doc][key])}
                for doc, key in references
            ],
        }
        answers[case.id, "baseline"] = {"outcome": case.expected_outcome, "grade": "pass"}
        for scenario in ADVERSARIAL.get(case.id, ()):
            answers[case.id, scenario.id] = {
                "outcome": case.expected_outcome,
                "grade": scenario.expected,
            }
    stimuli = {
        "baseline": {key: asdict(value) for key, value in BASE.items()},
        "adversarial": {
            key: [asdict(value) for value in values] for key, values in ADVERSARIAL.items()
        },
    }
    return {
        "dataset_sha256": digest(bundle.dataset.model_dump(mode="json")),
        "rubric_sha256": digest(load_json(RUBRIC_PATH)),
        "stimulus_sha256": digest(stimuli),
        "corpus_hashes": {doc.key: doc.revision_sha256 for doc in bundle.corpus.documents},
        "populations": {"retrieval": retrieval, "answer": answers},
        "pgvector_image": PGVECTOR_IMAGE,
        "python": python or platform.python_version(),
        "environment": environment or f"{platform.system()}-{platform.machine()}",
        "dependencies_sha256": dependencies_sha256
        or digest(
            sorted(
                (dist.metadata["Name"].lower(), dist.version)
                for dist in importlib.metadata.distributions()
            )
        ),
    }


def trusted_baselines(base, root=ROOT):
    token(base, "trusted_base", r"[a-f0-9]{40}")
    resolved = git("rev-parse", "--verify", f"{base}^{{commit}}", root=root)
    require(
        resolved.returncode == 0 and resolved.stdout.decode().strip() == base,
        "trusted_base_missing",
    )
    reports = {}
    for kind, path in PATHS.items():
        fetched = git("show", f"{base}:{path}", root=root)
        if fetched.returncode == 0:
            trusted = validate_baseline(parse_json(fetched.stdout))
            require(trusted["evaluation_type"] == kind, "trusted_baseline_type")
            require(
                validate_baseline(load_json(root / path)) == trusted,
                "candidate_baseline_replacement",
                "hard_failure",
            )
            reports[kind] = trusted
    if not reports:
        require(base == BOOTSTRAP_BASE, "trusted_baselines_missing", "hard_failure")
        require(
            git("diff", "--quiet", base, "--", *INPUTS, root=root).returncode == 0,
            "bootstrap_inputs_changed",
            "hard_failure",
        )
    else:
        require(set(reports) == set(TYPES), "trusted_baselines_incomplete", "hard_failure")
    return reports


def run_reports(root, output, context):
    normalized = {}
    statuses = {}
    for kind, module in RUNNERS.items():
        try:
            command = [sys.executable, "-B", "-m", module]
            if kind == "retrieval":
                command += ["--k", "5", "--min-score", "0.05"]
            process = subprocess.run(
                command,
                cwd=root / "backend",
                capture_output=True,
                check=False,
                timeout=180,
                env={
                    **os.environ,
                    "PYTHONPATH": str(root / "backend"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            statuses[kind] = {"runner_exit_code": process.returncode}
            report = parse_json(process.stdout)
            candidate = normalize_report(kind, report, context)
            # Publish the allowlisted source projection. Keep raw stdout and stderr in memory.
            write_json(output / f"{kind}.report.json", candidate)
            require(process.returncode == 0, "runner_nonzero_exit", "hard_failure")
            normalized[kind] = candidate
        except subprocess.TimeoutExpired:
            statuses[kind] = {
                "runner_exit_code": None,
                "error": "runner_timeout",
                "category": "hard_failure",
            }
        except ContractError as exc:
            statuses[kind]["error"] = exc.field
            statuses[kind]["category"] = exc.category
        except OSError:
            statuses[kind] = {
                "runner_exit_code": None,
                "error": "runner_start_or_output_error",
                "category": "hard_failure",
            }
    write_json(output / "execution.json", statuses)
    return normalized, statuses


def verify_bootstrap(base, context, output):
    with TemporaryDirectory(prefix="finsight-baseline-base-") as directory:
        checkout = Path(directory) / "checkout"
        added = git("worktree", "add", "--detach", str(checkout), base)
        require(added.returncode == 0, "trusted_checkout_failed", "hard_failure")
        try:
            trusted, _ = run_reports(checkout, output, context)
            require(set(trusted) == set(TYPES), "trusted_bootstrap_execution", "hard_failure")
            for kind, candidate in trusted.items():
                committed = validate_baseline(load_json(ROOT / PATHS[kind]))
                source = committed["source"]
                require(
                    source["git_commit"] == base and not source["working_tree_dirty"],
                    "bootstrap_provenance",
                    "hard_failure",
                )
                require(
                    candidate["source"]["git_commit"] == base
                    and not candidate["source"]["working_tree_dirty"],
                    "trusted_checkout_provenance",
                    "hard_failure",
                )
                # Compare both directions so even a weakened candidate baseline fails.
                require(
                    compare(candidate, committed)["exit_code"] == 0
                    and compare(committed, candidate)["exit_code"] == 0,
                    "candidate_baseline_replacement",
                    "hard_failure",
                )
            return trusted
        finally:
            removed = git("worktree", "remove", str(checkout))
            require(removed.returncode == 0, "trusted_checkout_cleanup", "hard_failure")


def promote(args):
    """Normalize two verified, clean source runs into a new review directory."""
    token(args.source_commit, "source_commit", r"[a-f0-9]{40}")
    require(
        git("rev-parse", "--verify", f"{args.source_commit}^{{commit}}").returncode == 0,
        "promotion_source_missing",
    )
    require(
        git("merge-base", "--is-ancestor", args.source_commit, "origin/master").returncode == 0,
        "promotion_source_not_on_master",
        "hard_failure",
    )
    require(
        git("diff", "--quiet", args.source_commit, "--", *INPUTS).returncode == 0,
        "promotion_inputs_differ",
        "hard_failure",
    )
    context = context_for_checkout(
        python=args.python,
        environment=args.environment,
        dependencies_sha256=digest(
            sorted(args.dependencies.read_text(encoding="utf-8").splitlines())
        ),
    )
    output = {}
    for kind in TYPES:
        reports = [
            normalize_report(kind, load_json(args.reports / f"{kind}-{index}.json"), context)
            for index in (1, 2)
        ]
        for report in reports:
            require(
                report["source"]["git_commit"] == args.source_commit
                and not report["source"]["working_tree_dirty"],
                "promotion_provenance",
                "hard_failure",
            )
        require(reports[0] == reports[1], "promotion_not_reproducible", "hard_failure")
        output[kind] = reports[0]
    args.output.mkdir(parents=True, exist_ok=False)
    for kind, report in output.items():
        write_json(args.output / Path(PATHS[kind]).name, report)
    return 0


def run(args):
    from evaluation.retrieval_runner import validate_test_database_url

    try:
        validate_test_database_url(os.getenv("TEST_DATABASE_URL"))
    except ValueError as exc:
        raise ContractError("unsafe_or_missing_test_database") from exc
    context = context_for_checkout()
    baseline = trusted_baselines(args.base_ref)
    if not baseline:
        trusted_output = args.output / "trusted"
        trusted_output.mkdir()
        baseline = verify_bootstrap(args.base_ref, context, trusted_output)
    candidates, statuses = run_reports(ROOT, args.output, context)
    codes = []
    for kind in TYPES:
        if kind in candidates:
            comparison = compare(baseline[kind], candidates[kind])
        else:
            status = statuses[kind]
            comparison = failure(kind, ContractError(status["error"], status["category"]))
        write_json(args.output / f"{kind}.comparison.json", comparison)
        codes.append(comparison["exit_code"])
    return next((code for code in (1, 2, 3) if code in codes), 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--base-ref", required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    promotion = sub.add_parser("promote")
    promotion.add_argument("--source-commit", required=True)
    promotion.add_argument("--reports", type=Path, required=True)
    promotion.add_argument("--python", required=True)
    promotion.add_argument("--environment", required=True)
    promotion.add_argument("--dependencies", type=Path, required=True)
    promotion.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output_created = False
    try:
        # Keep application settings synthetic even when the caller has a local .env.
        os.environ.update(
            APP_ENV="development",
            DATABASE_URL="sqlite://",
            JWT_SECRET_KEY="offline-eval-access-placeholder-1234567890",
            JWT_REFRESH_SECRET_KEY="offline-eval-refresh-placeholder-1234567890",
            OPENAI_API_KEY="offline-eval-placeholder-no-provider",
            OPENAI_MODEL="gpt-4o",
        )
        if args.command == "run":
            args.output.mkdir(parents=True, exist_ok=False)
            output_created = True
            return run(args)
        return promote(args)
    except (ContractError, OSError) as exc:
        if not isinstance(exc, ContractError):
            exc = ContractError("input_or_output_unavailable")
        summary = failure(None, exc)
        if output_created:
            write_json(args.output / "suite.failure.json", summary)
        print(json.dumps(summary, allow_nan=False))
        return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

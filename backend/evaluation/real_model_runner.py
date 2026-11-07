"""Manual real-model Document Q&A evaluation. Planning imports no application code."""

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from evaluation.real_model_contract import Budget, Profile, canonical, digest, plan_for

ROOT = Path(__file__).resolve().parents[2]


def atomic_write(path: Path, payload: bytes):
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def checkout():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def envelope(identity):
    return {"identity": identity, "sha256": digest(identity)}


def configuration(args):
    if not args.allow_paid:
        raise ValueError("Explicit --allow-paid is required")
    if args.command == "resume":
        directory = args.run_dir.resolve(strict=True)
        saved = json.loads((directory / "run_manifest.json").read_bytes())
        identity = saved["identity"]
        if saved != envelope(identity):
            raise ValueError("Run manifest digest differs")
        profile = Profile.model_validate(identity["profile"])
        budget = Budget.model_validate(identity["budget"])
    else:
        profile = Profile.model_validate_json(args.profile.read_bytes())
        budget = Budget(
            requests=args.max_requests,
            tokens=args.max_tokens,
            estimated_cost=args.max_estimated_cost,
        )
        directory = args.output.resolve()
        if directory.is_relative_to(ROOT):
            raise ValueError("Use a private output directory outside the checkout")
        identity = {
            "schema_version": 1,
            "run_id": uuid4().hex,
            "profile": profile.model_dump(mode="json"),
            "budget": budget.model_dump(mode="json"),
            "plan": plan_for(profile),
            "commit": checkout(),
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
    if directory.is_relative_to(ROOT):
        raise ValueError("Run directory must be outside the checkout")
    if identity["plan"] != plan_for(profile) or identity["commit"] != checkout():
        raise ValueError("Run plan or checkout differs")
    if budget.requests < identity["plan"]["request_upper_bound"]:
        raise ValueError("Request ceiling is below the complete plan")
    if budget.tokens < identity["plan"][
        "planning_token_reservation"
    ] or budget.estimated_cost < Decimal(identity["plan"]["planning_cost_reservation"]):
        raise ValueError(
            "Token or estimated cost ceiling is below the offline planning reservation"
        )
    return profile, budget, directory, identity


def run_async(coroutine):
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--profile", required=True, type=Path)
    run = commands.add_parser("run")
    run.add_argument("--profile", required=True, type=Path)
    run.add_argument("--allow-paid", action="store_true")
    run.add_argument("--max-requests", required=True, type=int)
    run.add_argument("--max-tokens", required=True, type=int)
    run.add_argument("--max-estimated-cost", required=True, type=Decimal)
    run.add_argument("--output", required=True, type=Path)
    resume = commands.add_parser("resume")
    resume.add_argument("--run-dir", required=True, type=Path)
    resume.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            print(
                canonical(plan_for(Profile.model_validate_json(args.profile.read_bytes()))).decode()
            )
            return 0
        profile, budget, directory, identity = configuration(args)
        credential = os.environ.get("FINSIGHT_EVAL_OPENAI_API_KEY", "")
        database = os.environ.get("FINSIGHT_EVAL_DATABASE_URL", "")
        if len(credential.strip()) < 10 or not database:
            raise ValueError("Set dedicated evaluation credential and database variables")
        synthetic = {
            "APP_ENV": "development",
            "DATABASE_URL": "sqlite://",
            "JWT_SECRET_KEY": uuid4().hex + uuid4().hex,
            "JWT_REFRESH_SECRET_KEY": uuid4().hex + uuid4().hex,
            "OPENAI_API_KEY": "offline-placeholder",
            "STORAGE_BACKEND": "local",
            "RATE_LIMIT_BACKEND": "memory",
        }
        with patch.dict(os.environ, synthetic):
            from evaluation.real_model_execution import execute
        from evaluation.real_model_provider import Journal

        if args.command == "run":
            directory.mkdir(mode=0o700)
            atomic_write(directory / "run_manifest.json", canonical(envelope(identity)))
        elif not (directory / "execution.sqlite3").is_file():
            raise ValueError("Resume requires an existing execution journal")
        journal = Journal(
            directory / "execution.sqlite3",
            {"manifest": digest(identity)},
            budget,
            resume=args.command == "resume",
        )
        try:
            journal.assert_resumable()
            summary = run_async(
                execute(profile, journal, credential, database, directory, identity)
            )
        finally:
            journal.db.close()
        return 0 if summary["completed"] == summary["planned"] and not summary["errors"] else 1
    except ValidationError:
        print("Invalid evaluation profile, budget, or artifact.", file=sys.stderr)
    except Exception:
        # Exception strings may contain HTTP data, connection URLs or secret values.
        print(
            "Evaluation stopped. Check opt-in, profile, budgets, dedicated database and journal.",
            file=sys.stderr,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

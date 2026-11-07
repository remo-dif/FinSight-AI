"""Compare normalized offline evaluation contracts."""

import argparse
import json
from pathlib import Path

from evaluation.baseline_contract import (
    TOLERANCE,
    ContractError,
    case_key,
    load_json,
    validate_baseline,
)


def result(kind, code, differences):
    return {
        "comparison_schema_version": 1,
        "evaluation_type": kind,
        "compatible": True if code in {0, 1} else False if code == 3 else None,
        "result": {0: "pass", 1: "fail", 2: "invalid", 3: "incompatible"}[code],
        "exit_code": code,
        "differences": differences,
    }


def difference(category, path, expected=None, observed=None, key=(), delta=None):
    return {
        "category": category,
        "field": path,
        "expected": expected,
        "observed": observed,
        "case": key[0] if key else None,
        "scenario": (key[1] or None) if key else None,
        "delta": delta,
    }


def failure(kind, exc):
    code = 1 if exc.category == "hard_failure" else 2
    return {**result(kind, code, [difference(exc.category, exc.field)]), "compatible": None}


def _compare_metrics(before, after, path, differences, key=()):
    for name in sorted(before.keys() | after.keys()):
        left, right = before.get(name), after.get(name)
        if (name in before) != (name in after) or (left is None) != (right is None):
            differences.append(difference("hard_failure", f"{path}.{name}", left, right, key))
        elif left is not None and abs(right - left) > TOLERANCE:
            category = "regression" if right < left else "improvement"
            differences.append(
                difference(category, f"{path}.{name}", left, right, key, right - left)
            )


def _aggregate_values(kind, report):
    if kind == "retrieval":
        return {
            f"{track}.{metric}": value
            for track, group in report["aggregates"].items()
            for metric, value in group["metrics"].items()
        }
    return {name: values["mean"] for name, values in report["aggregates"]["metrics"].items()}


def compare(baseline, candidate):
    try:
        baseline = validate_baseline(baseline)
        candidate = validate_baseline(candidate)
    except ContractError as exc:
        return failure(None, exc)
    kind = baseline["evaluation_type"]
    left = {"evaluation_type": kind, **baseline["identity"]}
    right = {"evaluation_type": candidate["evaluation_type"], **candidate["identity"]}
    changes = [
        difference("incompatible", name, left.get(name), right.get(name))
        for name in sorted(left.keys() | right.keys())
        if left.get(name) != right.get(name)
    ]
    if changes:
        return result(kind, 3, changes)

    before = {case_key(row): row for row in baseline["cases"]}
    after = {case_key(row): row for row in candidate["cases"]}
    differences = []
    for key in sorted(before.keys() | after.keys()):
        if key not in before or key not in after:
            differences.append(
                difference("hard_failure", "case_population", key in before, key in after, key)
            )
            continue
        previous, current = before[key], after[key]
        names = (previous.keys() | current.keys()) - {"id", "scenario", "metrics", "diagnostics"}
        for name in sorted(names):
            if previous.get(name) != current.get(name):
                differences.append(
                    difference("hard_failure", name, previous.get(name), current.get(name), key)
                )
        _compare_metrics(previous["metrics"], current["metrics"], "metrics", differences, key)
        for name in sorted(
            previous.get("diagnostics", {}).keys() | current.get("diagnostics", {}).keys()
        ):
            old = previous.get("diagnostics", {}).get(name)
            new = current.get("diagnostics", {}).get(name)
            if old != new:
                differences.append(difference("warning", f"diagnostics.{name}", old, new, key))
    _compare_metrics(
        _aggregate_values(kind, baseline),
        _aggregate_values(kind, candidate),
        "aggregates",
        differences,
    )
    code = int(any(item["category"] in {"hard_failure", "regression"} for item in differences))
    return result(kind, code, differences)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        comparison = compare(load_json(args.baseline), load_json(args.candidate))
    except ContractError as exc:
        comparison = failure(None, exc)
    print(json.dumps(comparison, indent=2, allow_nan=False))
    return comparison["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate serialized projections without database access or a second calculator."""

from datetime import date
from decimal import Decimal

from app.services.financial_context import reporting_currency

TOTAL_KEYS = ("income", "spending", "net_cash_flow", "net_spending", "refunds")


def money(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result != result.quantize(Decimal("0.01")):
        raise ValueError("Invalid monetary precision")
    return result


def references(value) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise TypeError("Invalid transaction references")
    if len(value) != len(set(value)):
        raise ValueError("Repeated transaction references")
    return set(value)


def validate_financial_report(report: dict) -> dict:
    evidence = report["_evidence"]
    if not isinstance(evidence, dict) or not isinstance(evidence.get("facts"), list):
        raise TypeError("Missing financial facts")
    currency = evidence["currency"]
    if reporting_currency(currency) != currency:
        raise ValueError("Invalid evidence currency")
    period = evidence["period"]
    if not isinstance(period, str):
        raise TypeError("Missing reporting period")
    if period != "all history":
        parts = period.split(" to ")
        if len(parts) not in {1, 2}:
            raise ValueError("Invalid reporting period")
        for part in parts:
            if len(part) != 7:
                raise ValueError("Invalid reporting month")
            date.fromisoformat(part + "-01")
    sources = references(evidence["source_transaction_ids"])
    facts = {}
    for fact in evidence["facts"]:
        key = fact["key"]
        if not isinstance(key, str) or key in facts:
            raise ValueError("Duplicate or invalid claim key")
        amount = money(fact["amount"])
        ids = references(fact["transaction_ids"])
        if (
            fact["currency"] != currency
            or fact["period"] != period
            or not ids <= sources
            or (amount != 0 and not ids)
        ):
            raise ValueError("Unsupported financial fact")
        entity = fact.get("entity")
        if entity is not None and (
            not isinstance(entity, dict)
            or entity.get("kind") not in {"merchant", "category"}
            or not isinstance(entity.get("name"), str)
        ):
            raise TypeError("Invalid imported entity")
        facts[key] = fact
    if "currency" in report and report["currency"] != currency:
        raise ValueError("Report currency differs from its facts")
    if "month" in report and (report["month"] or "all history") != period:
        raise ValueError("Report period differs from its facts")
    kind = evidence.get("kind")
    if kind == "comparison" or ("left" in report and "right" in report):
        _validate_comparison(report, facts, currency, period, sources)
    elif kind == "summary" or "categories" in report:
        for key in TOTAL_KEYS:
            if money(report[key]) != money(facts[key]["amount"]):
                raise ValueError("Aggregate differs from its fact")
        if money(report["net_cash_flow"]) != money(report["income"]) - money(report["spending"]):
            raise ValueError("Cash flow does not reconcile")
        categories = report["categories"]
        expected = {f"category:{k}": money(v) for k, v in categories.items()}
        if {k for k in facts if k.startswith("category:")} != set(expected):
            raise ValueError("Missing category facts")
        if any(money(facts[k]["amount"]) != value for k, value in expected.items()):
            raise ValueError("Category differs from its fact")
        if sum(expected.values(), Decimal("0.00")) != money(report["net_spending"]):
            raise ValueError("Category spending does not reconcile")
        if set(facts) != set(TOTAL_KEYS) | set(expected):
            raise ValueError("Unexpected summary facts")
    elif kind in {"category", "merchant", "budget"}:
        values = {k: v for k, v in report.items() if k != "_evidence"}
        if set(facts) != {f"{kind}:{key}" for key in values}:
            raise ValueError("Missing or unexpected grouping facts")
        if any(money(v) != money(facts[f"{kind}:{k}"]["amount"]) for k, v in values.items()):
            raise ValueError("Grouping totals do not reconcile")
    elif kind == "anomaly":
        items = report["anomalies"]
        if set(facts) != {f"anomaly:{i['transaction_id']}" for i in items}:
            raise ValueError("Anomalies do not match facts")
        for item in items:
            fact = facts[f"anomaly:{item['transaction_id']}"]
            if money(item["amount"]) != money(fact["amount"]) or fact["transaction_ids"] != [
                item["transaction_id"]
            ]:
                raise ValueError("Anomaly is not supported by its transaction")
    elif kind == "recurring":
        items = report["recurring"]
        if set(facts) != {f"recurring:{i['merchant']}" for i in items}:
            raise ValueError("Recurring estimates do not match facts")
        if any(
            Decimal(str(i["amount"])).quantize(Decimal("0.01"))
            != money(facts[f"recurring:{i['merchant']}"]["amount"])
            for i in items
        ):
            raise ValueError("Recurring averages do not reconcile")
    return facts


def _validate_comparison(report, facts, currency, period, sources):
    left, right = report["left"], report["right"]
    a, b = validate_financial_report(left), validate_financial_report(right)
    if (
        left["currency"] != currency
        or right["currency"] != currency
        or period != f"{left['month']} to {right['month']}"
    ):
        raise ValueError("Comparison context does not reconcile")
    if sources != set(left["_evidence"]["source_transaction_ids"]) | set(
        right["_evidence"]["source_transaction_ids"]
    ):
        raise ValueError("Comparison sources do not reconcile")
    if set(facts) != {f"delta:{key}" for key in a.keys() | b.keys()}:
        raise ValueError("Missing comparison facts")
    for key in a.keys() | b.keys():
        x, y = a.get(key), b.get(key)
        fact = facts[f"delta:{key}"]
        if money(fact["amount"]) != money(y["amount"] if y else "0") - money(
            x["amount"] if x else "0"
        ):
            raise ValueError("Comparison arithmetic does not reconcile")
        left_ids = set(x["transaction_ids"]) if x else set()
        right_ids = set(y["transaction_ids"]) if y else set()
        if (
            references(fact["left_transaction_ids"]) != left_ids
            or references(fact["right_transaction_ids"]) != right_ids
            or references(fact["transaction_ids"]) != left_ids | right_ids
        ):
            raise ValueError("Comparison transaction sides do not reconcile")
    for field, key in {
        "spending_delta": "spending",
        "cash_flow_delta": "net_cash_flow",
        "net_spending_delta": "net_spending",
    }.items():
        if money(report[field]) != money(facts[f"delta:{key}"]["amount"]):
            raise ValueError("Comparison total differs from its fact")

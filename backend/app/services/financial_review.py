"""Only application-rendered facts may appear in financial explanations."""

import json
from decimal import Decimal, InvalidOperation


def render_fact(fact: dict) -> str:
    """Assertion wording is code-owned; imported names are explicitly quoted data."""
    key = fact["key"]
    delta = key.startswith("delta:")
    base_key = key.removeprefix("delta:")
    kind, _, name = base_key.partition(":")
    titles = {
        "income": "Gross income", "spending": "Gross spending", "net_cash_flow": "Net cash flow",
        "net_spending": "Spending excluding internal transfers, less explicit refunds",
        "refunds": "Explicit refunds", "category": "Category spending",
        "merchant": "Gross merchant spending", "budget": "Estimated budget (all-history spending / 3)",
        "recurring": "Repeated-charge average (cadence unverified)", "anomaly": "Unusual transaction",
        "summary": "Summary value",
    }
    title = titles.get(kind, "Financial value")
    if delta:
        title = f"Change in {title}"
    entity = fact.get("entity")
    if entity is None and name and kind in {"category", "budget", "merchant", "recurring"}:
        entity = {"kind": "category" if kind in {"category", "budget"} else "merchant", "name": name}
    data = ""
    if entity:
        entity_kind = "category" if entity.get("kind") == "category" else "merchant"
        data = f" Imported {entity_kind} (untrusted data): {json.dumps(str(entity.get('name', '')), ensure_ascii=True)}."
    return f"{title}: {fact['currency']} {Decimal(fact['amount']):,.2f} ({fact['period']}).{data}"


def review_financial_draft(tool_results: dict, draft: str) -> tuple[str, str, str]:
    evidence = tool_results.get("_evidence")
    if not isinstance(evidence, dict):
        return (
            "rejected",
            "Rejected: missing verifiable financial evidence.",
            "I need verifiable transaction evidence before answering.",
        )
    facts = evidence.get("facts")
    if not isinstance(facts, list):
        return (
            "rejected",
            "Rejected: invalid financial evidence.",
            "I could not validate the financial evidence.",
        )
    by_id = {}
    try:
        if (
            not isinstance(evidence.get("source_transaction_ids"), list)
            or not isinstance(evidence.get("currency"), str)
            or not isinstance(evidence.get("period"), str)
        ):
            raise TypeError("Missing evidence context")
        source_ids = set(evidence["source_transaction_ids"])
        for fact in facts:
            amount = Decimal(fact["amount"])
            if (
                not amount.is_finite()
                or amount != amount.quantize(Decimal("0.01"))
                or fact["currency"] != evidence["currency"]
                or fact["period"] != evidence["period"]
                or not isinstance(fact["transaction_ids"], list)
                or not set(fact["transaction_ids"]) <= source_ids
                or (amount != 0 and not fact["transaction_ids"])
                or fact["key"] in by_id
            ):
                raise ValueError("Invalid fact")
            by_id[fact["key"]] = fact
    except (KeyError, TypeError, InvalidOperation, ValueError):
        return (
            "rejected",
            "Rejected: inconsistent financial evidence.",
            "I could not validate the financial evidence.",
        )
    used_fallback = False
    try:
        selection = json.loads(draft)
        if not isinstance(selection, dict):
            raise TypeError("Invalid selection")
        keys = selection["claim_ids"]
        if (
            set(selection) != {"claim_ids"}
            or not isinstance(keys, list)
            or not keys
            or any(not isinstance(k, str) or k not in by_id for k in keys)
        ):
            raise ValueError("Unsupported claim")
        # Do not permit selective omission of relevant evidence by the model.
        if set(keys) != set(by_id) or len(keys) != len(by_id):
            raise ValueError("Incomplete claims")
        selected_facts = [by_id[key] for key in keys]
    except (ValueError, TypeError, KeyError):
        used_fallback = True
        selected_facts = facts
    if not facts:
        answer = f"No matching financial facts for {evidence['period']} ({evidence['currency']})."
    else:
        answer = " ".join(render_fact(f) for f in selected_facts)
    review = "Accepted: amounts, currency, periods and transaction references come from deterministic tool evidence."
    if used_fallback:
        review += " Unverified AI draft replaced with a deterministic explanation."
    return "accepted", review, answer

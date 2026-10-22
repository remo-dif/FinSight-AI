"""Only application-rendered facts may appear in financial explanations."""

import json
from decimal import Decimal, InvalidOperation


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
        answer = " ".join(
            f"{f['label']}: {f['currency']} {Decimal(f['amount']):,.2f} ({f['period']})."
            for f in selected_facts
        )
    review = "Accepted: amounts, currency, periods and transaction references come from deterministic tool evidence."
    if used_fallback:
        review += " Unverified AI draft replaced with a deterministic explanation."
    return "accepted", review, answer

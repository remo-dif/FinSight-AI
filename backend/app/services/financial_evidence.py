"""Deterministic financial facts. No inference from merchant names or document text."""

from collections import defaultdict
from decimal import Decimal

RULE_VERSION = "cash-flow-v1"
TRANSFER_CATEGORY = "Internal Transfer"
REFUND_PREFIX = "Refund:"


def spending_report(rows, currency: str, month: str | None) -> dict:
    zero = Decimal("0.00")
    income = sum((r.amount for r in rows if r.amount > 0), zero)
    spending = sum((-r.amount for r in rows if r.amount < 0), zero)
    categories = defaultdict(lambda: zero)
    category_ids = defaultdict(list)
    fingerprints = defaultdict(list)
    refunds = zero
    transfer_ids = []
    spending_ids = []
    for row in rows:
        row_id = str(row.id)
        fingerprints[
            (
                row.posted_at,
                row.merchant,
                row.description,
                row.amount,
                row.currency.upper(),
                row.category,
            )
        ].append(row_id)
        if row.category == TRANSFER_CATEGORY:
            transfer_ids.append(row_id)
        elif row.category.startswith(REFUND_PREFIX) and row.amount > 0:
            category = row.category[len(REFUND_PREFIX) :] or "Uncategorized"
            refunds += row.amount
            categories[category] -= row.amount
            category_ids[category].append(row_id)
            spending_ids.append(row_id)
        elif row.amount < 0:
            categories[row.category] -= row.amount
            category_ids[row.category].append(row_id)
            spending_ids.append(row_id)
    net_spending = sum(categories.values(), zero)
    facts = []

    def fact(key, label, amount, ids):
        facts.append(
            {
                "key": key,
                "label": label,
                "amount": f"{amount:.2f}",
                "currency": currency,
                "period": month or "all history",
                "transaction_ids": sorted(ids),
            }
        )

    fact("income", "Gross income", income, [str(r.id) for r in rows if r.amount > 0])
    fact("spending", "Gross spending", spending, [str(r.id) for r in rows if r.amount < 0])
    fact("net_cash_flow", "Net cash flow", income - spending, [str(r.id) for r in rows])
    fact(
        "net_spending",
        "Spending excluding internal transfers, less explicit refunds",
        net_spending,
        spending_ids,
    )
    fact(
        "refunds",
        "Explicit refunds",
        refunds,
        [
            str(r.id)
            for r in rows
            if r.category.startswith(REFUND_PREFIX)
            and r.amount > 0
            and r.category != TRANSFER_CATEGORY
        ],
    )
    for category, amount in sorted(categories.items()):
        fact(
            f"category:{category}",
            f"Category spending ({category})",
            amount,
            category_ids[category],
        )
    return {
        "month": month,
        "currency": currency,
        "income": f"{income:.2f}",
        "spending": f"{spending:.2f}",
        "net_cash_flow": f"{income - spending:.2f}",
        "net_spending": f"{net_spending:.2f}",
        "refunds": f"{refunds:.2f}",
        "categories": {k: f"{v:.2f}" for k, v in sorted(categories.items())},
        "internal_transfer_ids": sorted(transfer_ids),
        "suspected_duplicate_ids": sorted(
            i for group in fingerprints.values() if len(group) > 1 for i in group
        ),
        "_evidence": {
            "rule_version": RULE_VERSION,
            "currency": currency,
            "period": month or "all history",
            "facts": facts,
            "source_transaction_ids": sorted(str(r.id) for r in rows),
        },
    }


def comparison_report(left: dict, right: dict) -> dict:
    if left["currency"] != right["currency"]:
        raise ValueError("Cannot compare different currencies")
    facts = []
    left_facts = {f["key"]: f for f in left["_evidence"]["facts"]}
    right_facts = {f["key"]: f for f in right["_evidence"]["facts"]}
    for key in sorted(left_facts.keys() | right_facts.keys()):
        a, b = left_facts.get(key), right_facts.get(key)
        facts.append(
            {
                "key": f"delta:{key}",
                "label": f"Change in {(b or a)['label']}",
                "amount": f"{Decimal(b['amount'] if b else '0') - Decimal(a['amount'] if a else '0'):.2f}",
                "currency": left["currency"],
                "period": f"{left['month']} to {right['month']}",
                "transaction_ids": sorted(
                    set((a["transaction_ids"] if a else []) + (b["transaction_ids"] if b else []))
                ),
                "left_transaction_ids": a["transaction_ids"] if a else [],
                "right_transaction_ids": b["transaction_ids"] if b else [],
            }
        )
    return {
        "left": left,
        "right": right,
        "spending_delta": f"{Decimal(right['spending']) - Decimal(left['spending']):.2f}",
        "cash_flow_delta": f"{Decimal(right['net_cash_flow']) - Decimal(left['net_cash_flow']):.2f}",
        "net_spending_delta": f"{Decimal(right['net_spending']) - Decimal(left['net_spending']):.2f}",
        "_evidence": {
            "rule_version": RULE_VERSION,
            "currency": left["currency"],
            "period": f"{left['month']} to {right['month']}",
            "facts": facts,
            "source_transaction_ids": sorted(
                set(
                    left["_evidence"]["source_transaction_ids"]
                    + right["_evidence"]["source_transaction_ids"]
                )
            ),
        },
    }

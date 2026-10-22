import json
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from app.services.analytics import FinanceAnalyticsService


class FinanceToolLayer:
    def __init__(self, analytics: FinanceAnalyticsService) -> None:
        self.analytics = analytics
        self.month: str | None = None
        self.currency: str | None = None
        self._trusted_payload_json: str | None = None

    def _publish(self, result: dict) -> dict:
        # Capture the one calculation before passing a mutable projection to generation.
        evidence = result.get("_evidence", {})
        kind = evidence.get("kind")
        if kind in {"category", "merchant", "budget"}:
            # Preserve every imported key, including the reserved envelope name.
            evidence["group_totals"] = {f["key"][len(kind) + 1:]: f["amount"] for f in evidence["facts"]}
        self._trusted_payload_json = json.dumps(result, sort_keys=True)
        return result

    def matches_snapshot(self, result: dict) -> bool:
        try:
            return (
                self._trusted_payload_json is not None
                and json.dumps(result, sort_keys=True) == self._trusted_payload_json
            )
        except (TypeError, ValueError):
            return False

    def configure_context(self, month: str | None, currency: str | None) -> None:
        self.month, self.currency = month, currency

    def get_transactions(self, user_id: UUID) -> dict:
        rows = self.analytics.repository.list_for_user(user_id, limit=50)
        return {
            "transactions": [
                {
                    "id": str(r.id),
                    "currency": r.currency,
                    "merchant": r.merchant,
                    "amount": str(r.amount),
                    "date": r.posted_at.isoformat(),
                    "category": r.category,
                }
                for r in rows
            ]
        }

    def get_monthly_summary(self, user_id: UUID, month: str) -> dict:
        return self._publish(self.analytics.get_spending_report(user_id, month, self.currency))

    def compare_months(self, user_id: UUID, left_month: str, right_month: str) -> dict:
        return self._publish(
            self.analytics.compare_spending(user_id, left_month, right_month, self.currency)
        )

    def get_spending_by_category(self, user_id: UUID) -> dict:
        report = self.analytics.get_spending_report(user_id, self.month, self.currency)
        evidence = dict(report["_evidence"])
        evidence["kind"] = "category"
        evidence["facts"] = [f for f in evidence["facts"] if f["key"].startswith("category:")]
        return self._publish({**report["categories"], "_evidence": evidence})

    def detect_anomalies(self, user_id: UUID) -> dict:
        currency, rows = self.analytics.repository.rows_for_analysis(
            user_id, month=self.month, currency=self.currency
        )
        items = [item.model_dump(mode="json") for item in self.analytics.anomalies_for_rows(rows)]
        facts = [
            {
                "key": f"anomaly:{item['transaction_id']}",
                "label": f"Unusual transaction ({item['merchant']})",
                "entity": {"kind": "merchant", "name": item["merchant"]},
                "amount": str(item["amount"]),
                "currency": currency,
                "period": self.month or "all history",
                "transaction_ids": [item["transaction_id"]],
            }
            for item in items
        ]
        return self._publish(
            {
                "anomalies": items,
                "_evidence": self._evidence(
                    currency, self.month or "all history", facts, rows, "anomaly"
                ),
            }
        )

    def generate_budget(self, user_id: UUID) -> dict:
        # Preserve the legacy history / 3 rule, explicitly labelled as an estimate.
        currency, rows = self.analytics.repository.rows_for_analysis(
            user_id, currency=self.currency
        )
        amounts = defaultdict(lambda: Decimal("0.00"))
        for row in rows:
            if row.amount < 0:
                amounts[row.category] -= row.amount
        values = {k: (v / Decimal(3)).quantize(Decimal("0.01")) for k, v in amounts.items()}
        facts = [
            {
                "key": f"budget:{k}",
                "label": f"Estimated budget ({k}; all-history spending / 3)",
                "amount": str(v),
                "currency": currency,
                "period": "all history",
                "transaction_ids": sorted(
                    str(r.id) for r in rows if r.category == k and r.amount < 0
                ),
            }
            for k, v in sorted(values.items())
        ]
        return self._publish(
            {
                **{k: str(v) for k, v in values.items()},
                "_evidence": self._evidence(currency, "all history", facts, rows, "budget"),
            }
        )

    def get_top_merchants(self, user_id: UUID) -> dict:
        currency, rows = self.analytics.repository.rows_for_analysis(
            user_id, month=self.month, currency=self.currency
        )
        totals = defaultdict(lambda: Decimal("0.00"))
        for row in rows:
            if row.amount < 0:
                totals[row.merchant] -= row.amount
        values = dict(sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:10])
        facts = [
            {
                "key": f"merchant:{k}",
                "label": f"Gross merchant spending ({k})",
                "amount": str(v),
                "currency": currency,
                "period": self.month or "all history",
                "transaction_ids": sorted(
                    str(r.id) for r in rows if r.merchant == k and r.amount < 0
                ),
            }
            for k, v in values.items()
        ]
        return self._publish(
            {
                **{k: str(v) for k, v in values.items()},
                "_evidence": self._evidence(
                    currency, self.month or "all history", facts, rows, "merchant"
                ),
            }
        )

    def get_recurring_payments(self, user_id: UUID) -> dict:
        currency, rows = self.analytics.repository.rows_for_analysis(
            user_id, currency=self.currency
        )
        items = [item.model_dump(mode="json") for item in self.analytics.recurring_for_rows(rows)]
        facts = [
            {
                "key": f"recurring:{item['merchant']}",
                "label": f"Repeated-charge average ({item['merchant']}; cadence unverified)",
                "amount": f"{Decimal(item['amount']):.2f}",
                "currency": currency,
                "period": "all history",
                "transaction_ids": sorted(
                    str(r.id) for r in rows if r.merchant == item["merchant"] and r.amount < 0
                ),
            }
            for item in items
        ]
        return self._publish(
            {
                "recurring": items,
                "_evidence": self._evidence(currency, "all history", facts, rows, "recurring"),
            }
        )

    @staticmethod
    def _evidence(currency, period, facts, rows, kind):
        return {
            "kind": kind,
            "rule_version": "cash-flow-v1",
            "currency": currency,
            "period": period,
            "facts": facts,
            "source_transaction_ids": sorted(str(r.id) for r in rows),
        }

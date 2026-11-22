from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from heapq import heappop, heappush
from itertools import groupby
from typing import Protocol
from uuid import UUID

from app.schemas.risk import RiskSignal


class RiskTransaction(Protocol):
    id: UUID
    posted_at: date
    merchant: str
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class RiskSignalConfig:
    duplicate_window_days: int = 3
    velocity_minimum_payments: int = 3
    amount_minimum_history: int = 4
    amount_multiplier: Decimal = Decimal(3)
    new_merchant_minimum_prior_payments: int = 5
    max_transaction_references: int = 25

    def __post_init__(self) -> None:
        integers = (
            self.duplicate_window_days,
            self.velocity_minimum_payments,
            self.amount_minimum_history,
            self.new_merchant_minimum_prior_payments,
            self.max_transaction_references,
        )
        if (
            any(type(value) is not int or value < 1 for value in integers)
            or not isinstance(self.amount_multiplier, Decimal)
            or not self.amount_multiplier.is_finite()
            or self.amount_multiplier <= 1
        ):
            raise ValueError("Risk signal thresholds must be positive and multiplier must exceed 1")


def _merchant_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _merchant_display(value: str) -> str:
    return " ".join(value.split())


def _payments(rows: Iterable[RiskTransaction]) -> list[RiskTransaction]:
    unique: dict[UUID, RiskTransaction] = {}
    for row in rows:
        if not isinstance(row.amount, Decimal) or not row.amount.is_finite():
            raise ValueError("Transaction amounts must be finite Decimal values")
        existing = unique.get(row.id)
        if existing is not None and (
            existing.posted_at,
            existing.merchant,
            existing.amount,
            existing.currency,
        ) != (row.posted_at, row.merchant, row.amount, row.currency):
            raise ValueError("Conflicting transaction records share the same identifier")
        unique.setdefault(row.id, row)
    return sorted(
        (row for row in unique.values() if row.amount < 0),
        key=lambda row: (row.posted_at, str(row.id)),
    )


def _references(
    rows: list[RiskTransaction],
    config: RiskSignalConfig,
    terminal: RiskTransaction | None = None,
) -> list[UUID]:
    limit = config.max_transaction_references
    if len(rows) <= limit:
        return [row.id for row in rows]
    if terminal is None:
        return [row.id for row in rows[:limit]]
    earlier = [row.id for row in rows if row.id != terminal.id]
    return [*earlier[: max(0, limit - 1)], terminal.id]


def _duplicate_signals(rows: list[RiskTransaction], config: RiskSignalConfig) -> list[RiskSignal]:
    grouped: dict[tuple[str, Decimal, str], list[RiskTransaction]] = defaultdict(list)
    for row in rows:
        grouped[(_merchant_key(row.merchant), abs(row.amount), row.currency)].append(row)

    signals: list[RiskSignal] = []
    for (merchant, amount, currency), candidates in sorted(grouped.items()):
        cluster: list[RiskTransaction] = []
        for row in candidates:
            if (
                cluster
                and (row.posted_at - cluster[-1].posted_at).days > config.duplicate_window_days
            ):
                if len(cluster) > 1:
                    signals.append(_duplicate_signal(cluster, merchant, amount, currency, config))
                cluster = []
            cluster.append(row)
        if len(cluster) > 1:
            signals.append(_duplicate_signal(cluster, merchant, amount, currency, config))
    return signals


def _duplicate_signal(rows, merchant, amount, currency, config) -> RiskSignal:
    references = _references(rows, config, terminal=rows[-1])
    return RiskSignal(
        signal_id="duplicate_payment_candidate_v1",
        signal_type="duplicate_payment_candidate",
        observed_at=rows[-1].posted_at,
        explanation=(
            "Payments form a consecutive chain sharing normalized merchant, amount and "
            "currency, with each neighboring date inside the configured window; review "
            "for a possible duplicate, not confirmed fraud."
        ),
        evidence={
            "merchant_normalized": merchant,
            "amount": f"{amount:.2f}",
            "currency": currency,
            "payment_count": len(rows),
            "cluster_span_days": (rows[-1].posted_at - rows[0].posted_at).days,
            "referenced_payment_count": len(references),
            "references_truncated": len(references) < len(rows),
        },
        transaction_ids=references,
        thresholds={"window_days": config.duplicate_window_days},
        risk_level="medium",
    )


def _velocity_signals(rows: list[RiskTransaction], config: RiskSignalConfig) -> list[RiskSignal]:
    grouped: dict[tuple[date, str], list[RiskTransaction]] = defaultdict(list)
    for row in rows:
        grouped[(row.posted_at, row.currency)].append(row)
    signals: list[RiskSignal] = []
    for (day, currency), items in sorted(grouped.items()):
        if len(items) < config.velocity_minimum_payments:
            continue
        references = _references(items, config)
        signals.append(
            RiskSignal(
                signal_id="daily_velocity_v1",
                signal_type="daily_velocity",
                observed_at=day,
                explanation=(
                    "Payment count in one currency reached the configured daily threshold; "
                    "review the concentration, not as confirmed fraud."
                ),
                evidence={
                    "currency": currency,
                    "payment_count": len(items),
                    "referenced_payment_count": len(references),
                    "references_truncated": len(references) < len(items),
                },
                transaction_ids=references,
                thresholds={
                    "minimum_payments": config.velocity_minimum_payments,
                    "window_days": 1,
                },
                risk_level="medium",
            )
        )
    return signals


class _RunningMedian:
    def __init__(self) -> None:
        self.lower: list[Decimal] = []
        self.upper: list[Decimal] = []

    def add(self, value: Decimal) -> None:
        if not self.lower or value <= -self.lower[0]:
            heappush(self.lower, -value)
        else:
            heappush(self.upper, value)
        if len(self.lower) > len(self.upper) + 1:
            heappush(self.upper, -heappop(self.lower))
        elif len(self.upper) > len(self.lower):
            heappush(self.lower, -heappop(self.upper))

    def value(self) -> Decimal:
        if len(self.lower) == len(self.upper):
            return (-self.lower[0] + self.upper[0]) / Decimal(2)
        return -self.lower[0]

    def __len__(self) -> int:
        return len(self.lower) + len(self.upper)


def _amount_deviation_signals(
    rows: list[RiskTransaction], config: RiskSignalConfig
) -> list[RiskSignal]:
    grouped: dict[tuple[str, str], list[RiskTransaction]] = defaultdict(list)
    for row in rows:
        grouped[(_merchant_key(row.merchant), row.currency)].append(row)

    signals: list[RiskSignal] = []
    for (merchant, currency), items in sorted(grouped.items()):
        history = _RunningMedian()
        history_references: list[RiskTransaction] = []
        for _, same_day in groupby(items, key=lambda item: item.posted_at):
            day_items = list(same_day)
            if len(history) >= config.amount_minimum_history:
                baseline = history.value()
                for row in day_items:
                    observed = abs(row.amount)
                    if baseline <= 0 or observed < baseline * config.amount_multiplier:
                        continue
                    references = _references([*history_references, row], config, terminal=row)
                    signals.append(
                        RiskSignal(
                            signal_id="merchant_amount_deviation_v1",
                            signal_type="amount_deviation",
                            observed_at=row.posted_at,
                            explanation=(
                                "Payment amount exceeds the configured multiple of the prior "
                                "same-merchant, same-currency median; review as an anomaly."
                            ),
                            evidence={
                                "merchant_normalized": merchant,
                                "currency": currency,
                                "baseline_amount": f"{baseline:.2f}",
                                "observed_amount": f"{observed:.2f}",
                                "history_count": len(history),
                                "referenced_history_count": len(references) - 1,
                                "references_truncated": (len(references) - 1 < len(history)),
                            },
                            transaction_ids=references,
                            thresholds={
                                "minimum_history": config.amount_minimum_history,
                                "multiplier": str(config.amount_multiplier),
                            },
                            risk_level="high",
                        )
                    )
            for row in day_items:
                history.add(abs(row.amount))
                if len(history_references) < max(0, config.max_transaction_references - 1):
                    history_references.append(row)
    return signals


def _new_merchant_signals(
    rows: list[RiskTransaction], config: RiskSignalConfig
) -> list[RiskSignal]:
    by_currency: dict[str, list[RiskTransaction]] = defaultdict(list)
    for row in rows:
        by_currency[row.currency].append(row)

    signals: list[RiskSignal] = []
    for currency, items in sorted(by_currency.items()):
        seen: set[str] = set()
        prior_count = 0
        for _, same_day in groupby(items, key=lambda item: item.posted_at):
            day_items = list(same_day)
            first_today: dict[str, RiskTransaction] = {}
            for row in day_items:
                merchant = _merchant_key(row.merchant)
                if merchant not in seen:
                    first_today.setdefault(merchant, row)
            if prior_count >= config.new_merchant_minimum_prior_payments:
                for merchant, row in sorted(first_today.items()):
                    signals.append(
                        RiskSignal(
                            signal_id="new_merchant_v1",
                            signal_type="new_merchant",
                            observed_at=row.posted_at,
                            explanation=(
                                "This is the first observed payment to the normalized merchant "
                                "after sufficient prior currency history; new does not imply "
                                "fraudulent."
                            ),
                            evidence={
                                "merchant": _merchant_display(row.merchant),
                                "merchant_normalized": merchant,
                                "currency": currency,
                                "prior_payment_count": prior_count,
                            },
                            transaction_ids=[row.id],
                            thresholds={
                                "minimum_prior_payments": (
                                    config.new_merchant_minimum_prior_payments
                                )
                            },
                            risk_level="low",
                        )
                    )
            seen.update(first_today)
            prior_count += len(day_items)
    return signals


def evaluate_risk_signals(
    rows: Iterable[RiskTransaction], config: RiskSignalConfig | None = None
) -> list[RiskSignal]:
    policy = config or RiskSignalConfig()
    selected = _payments(rows)
    signals = [
        *_duplicate_signals(selected, policy),
        *_velocity_signals(selected, policy),
        *_amount_deviation_signals(selected, policy),
        *_new_merchant_signals(selected, policy),
    ]
    return sorted(
        signals,
        key=lambda signal: (
            signal.observed_at,
            signal.signal_type,
            tuple(str(item) for item in signal.transaction_ids),
        ),
    )

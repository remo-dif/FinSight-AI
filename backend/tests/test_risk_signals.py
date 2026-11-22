from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.risk_signals import RiskSignalConfig, evaluate_risk_signals
from tests.fixtures.fraud_risk import transaction


def by_type(signals, signal_type):
    return [signal for signal in signals if signal.signal_type == signal_type]


def test_duplicate_candidate_normalizes_merchant_and_respects_date_and_currency():
    rows = [
        transaction("a", "2026-01-10", "  ACME   Supplies ", "-120.00"),
        transaction("b", "2026-01-11", "acme supplies", "-120.00"),
        transaction("outside", "2026-02-10", "ACME SUPPLIES", "-120.00"),
        transaction("usd", "2026-01-11", "ACME SUPPLIES", "-120.00", "USD"),
        transaction("income", "2026-01-11", "ACME SUPPLIES", "120.00"),
    ]

    signals = by_type(evaluate_risk_signals(rows), "duplicate_payment_candidate")

    assert len(signals) == 1
    assert signals[0].signal_id == "duplicate_payment_candidate_v1"
    assert signals[0].transaction_ids == [rows[0].id, rows[1].id]
    assert signals[0].fraud_determination is False
    assert signals[0].thresholds == {"window_days": 3}


def test_monthly_recurring_payments_are_not_duplicate_candidates():
    rows = [
        transaction("jan", "2026-01-01", "Cloud", "-15.00"),
        transaction("feb", "2026-02-01", "Cloud", "-15.00"),
        transaction("mar", "2026-03-01", "Cloud", "-15.00"),
    ]

    assert not by_type(evaluate_risk_signals(rows), "duplicate_payment_candidate")


def test_daily_velocity_is_currency_scoped_and_deterministic():
    rows = [
        transaction("c", "2026-04-03", "C", "-10.00"),
        transaction("a", "2026-04-03", "A", "-10.00"),
        transaction("b", "2026-04-03", "B", "-10.00"),
        transaction("usd", "2026-04-03", "D", "-10.00", "USD"),
    ]

    first = evaluate_risk_signals(rows)
    second = evaluate_risk_signals(list(reversed(rows)))
    velocity = by_type(first, "daily_velocity")

    assert first == second
    assert len(velocity) == 1
    assert velocity[0].thresholds == {"minimum_payments": 3, "window_days": 1}
    assert set(velocity[0].transaction_ids) == {rows[0].id, rows[1].id, rows[2].id}


def test_amount_deviation_uses_prior_same_merchant_currency_history():
    rows = [
        transaction(f"history-{index}", f"2026-01-0{index + 1}", "Vendor", "-10.00")
        for index in range(4)
    ]
    outlier = transaction("outlier", "2026-01-10", " vendor ", "-40.00")
    other_currency = transaction("usd-history", "2026-01-09", "Vendor", "-1000.00", "USD")

    signals = by_type(evaluate_risk_signals([outlier, other_currency, *rows]), "amount_deviation")

    assert len(signals) == 1
    assert signals[0].transaction_ids[-1] == outlier.id
    assert signals[0].evidence["baseline_amount"] == "10.00"
    assert signals[0].evidence["observed_amount"] == "40.00"
    assert signals[0].transaction_ids == [row.id for row in rows] + [outlier.id]
    assert signals[0].thresholds == {"minimum_history": 4, "multiplier": "3"}


def test_amount_deviation_abstains_when_history_is_insufficient():
    rows = [
        transaction("h1", "2026-01-01", "Vendor", "-10.00"),
        transaction("h2", "2026-01-02", "Vendor", "-10.00"),
        transaction("outlier", "2026-01-03", "Vendor", "-100.00"),
    ]

    assert not by_type(evaluate_risk_signals(rows), "amount_deviation")


def test_new_merchant_requires_prior_currency_scoped_history():
    history = [
        transaction(f"known-{index}", f"2026-01-0{index + 1}", "Known", "-10.00")
        for index in range(5)
    ]
    new = transaction("new", "2026-01-10", "New Supplier", "-25.00")
    early = transaction("early-new", "2026-01-01", "Early", "-30.00")

    signals = by_type(evaluate_risk_signals([new, *history, early]), "new_merchant")

    assert len(signals) == 1
    assert signals[0].transaction_ids == [new.id]
    assert signals[0].evidence["merchant"] == "New Supplier"
    assert signals[0].thresholds == {"minimum_prior_payments": 5}


def test_configurable_thresholds_change_behavior_without_float_arithmetic():
    rows = [
        transaction("one", "2026-01-01", "Vendor", "-10.00"),
        transaction("two", "2026-01-05", "Vendor", "-10.00"),
    ]
    config = RiskSignalConfig(
        duplicate_window_days=5,
        velocity_minimum_payments=10,
        amount_minimum_history=10,
        amount_multiplier=Decimal("2.5"),
        new_merchant_minimum_prior_payments=10,
    )

    signals = by_type(evaluate_risk_signals(rows, config), "duplicate_payment_candidate")

    assert len(signals) == 1
    assert signals[0].thresholds["window_days"] == 5


def test_same_transaction_record_is_not_counted_twice():
    row = transaction("same", "2026-01-01", "Vendor", "-10.00")

    assert evaluate_risk_signals([row, row]) == []


def test_conflicting_records_with_same_identifier_fail_closed_in_any_order():
    row = transaction("same", "2026-01-01", "Vendor", "-10.00")
    conflicting = replace(row, merchant="Different vendor")

    for records in ([row, conflicting], [conflicting, row]):
        with pytest.raises(ValueError, match="Conflicting transaction"):
            evaluate_risk_signals(records)


def test_conflicting_positive_and_negative_records_with_same_identifier_fail_closed():
    payment = transaction("same-sign", "2026-01-01", "Vendor", "-10.00")
    income = replace(payment, amount=Decimal("10.00"))

    with pytest.raises(ValueError, match="Conflicting transaction"):
        evaluate_risk_signals([income, payment])


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), 10.0])
def test_non_finite_or_non_decimal_transaction_amounts_fail_closed(amount):
    row = replace(transaction("invalid-amount", "2026-01-01", "Vendor", "-10.00"), amount=amount)

    with pytest.raises(ValueError, match="finite Decimal"):
        evaluate_risk_signals([row])


def test_duplicate_candidate_keeps_overlapping_window_connections():
    rows = [
        transaction("day-1", "2026-01-01", "Vendor", "-10.00"),
        transaction("day-4", "2026-01-04", "Vendor", "-10.00"),
        transaction("day-7", "2026-01-07", "Vendor", "-10.00"),
    ]

    signals = by_type(evaluate_risk_signals(rows), "duplicate_payment_candidate")

    assert len(signals) == 1
    assert signals[0].transaction_ids == [row.id for row in rows]


def test_large_evidence_sets_are_bounded_and_report_truncation():
    rows = [
        transaction(f"row-{index}", f"2026-01-{(index % 28) + 1:02d}", "Vendor", "-10.00")
        for index in range(100)
    ]
    config = RiskSignalConfig(max_transaction_references=10)

    duplicate = by_type(evaluate_risk_signals(rows, config), "duplicate_payment_candidate")[0]

    assert len(duplicate.transaction_ids) == 10
    assert duplicate.evidence["payment_count"] == 100
    assert duplicate.evidence["references_truncated"] is True


def test_truncated_duplicate_evidence_keeps_cluster_terminal_record():
    rows = [
        transaction(f"chain-{day}", f"2026-01-0{day}", "Vendor", "-10.00") for day in range(1, 5)
    ]

    duplicate = by_type(
        evaluate_risk_signals(rows, RiskSignalConfig(max_transaction_references=2)),
        "duplicate_payment_candidate",
    )[0]

    assert duplicate.transaction_ids == [rows[0].id, rows[-1].id]
    assert duplicate.evidence["cluster_span_days"] == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"duplicate_window_days": 0},
        {"velocity_minimum_payments": 0},
        {"amount_minimum_history": 0},
        {"amount_multiplier": Decimal(1)},
        {"amount_multiplier": Decimal("NaN")},
        {"amount_multiplier": Decimal("Infinity")},
        {"amount_multiplier": 2.5},
        {"duplicate_window_days": True},
        {"new_merchant_minimum_prior_payments": 0},
        {"max_transaction_references": 0},
    ],
)
def test_invalid_thresholds_fail_closed(overrides):
    with pytest.raises(ValueError, match="thresholds"):
        RiskSignalConfig(**overrides)

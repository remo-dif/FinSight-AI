"""Reproducible EUR ledger and independent integer-cent oracle.

Export without connecting to a database: python -m tests.fixtures.synthetic_finance
"""

import json
import random
from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

SEED = 20251022


def generate_dataset(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    users, transactions, expected = [], [], {}
    for user_index in range(10):
        user_id = str(uuid5(NAMESPACE_URL, f"finsight-synthetic/user/{user_index}"))
        users.append(
            {
                "id": user_id,
                "email": f"synthetic-{user_index}@example.invalid",
                "full_name": f"Synthetic User {user_index}",
            }
        )
        for month in range(1, 13):
            period = f"2025-{month:02d}"
            oracle = {"income": 0, "spending": 0, "refunds": 0, "net_spending": 0}
            categories = defaultdict(int)
            entries = [
                ("Salary", "Income", 280000 + user_index * 13000, "income"),
                ("Rent", "Housing", -(80000 + user_index * 1500), "expense"),
                ("Utilities", "Utilities", -rng.randint(8000, 18000), "expense"),
                ("Music", "Subscriptions", -1099, "expense"),
                ("Video", "Subscriptions", -1599, "expense"),
            ]
            entries += [
                (f"Transit {i}", "Transportation", -rng.randint(200, 4500), "expense")
                for i in range(3)
            ]
            entries += [
                (f"Restaurant {i}", "Restaurants", -rng.randint(1200, 7000), "expense")
                for i in range(4)
            ]
            entries += [
                (f"Grocer {i}", "Groceries", -rng.randint(1800, 11000), "expense") for i in range(8)
            ]
            entries += [
                ("Grocer refund", "Refund:Groceries", 1500, "refund"),
                ("Own savings", "Internal Transfer", -20000, "transfer"),
                ("Own current account", "Internal Transfer", 20000, "transfer"),
                entries[12],  # Deliberately identical grocery observation; retained.
                ("Unexpected purchase", "Shopping", -150000 if month == 8 else -2500, "expense"),
            ]
            assert len(entries) == 25
            for index, (merchant, category, cents, kind) in enumerate(entries):
                # Duplicate uses the original posting date and description.
                day = 13 if index == 23 else index + 1
                row = {
                    "id": str(uuid5(NAMESPACE_URL, f"{user_id}/{period}/{index}")),
                    "user_id": user_id,
                    "posted_at": f"{period}-{day:02d}",
                    "merchant": merchant,
                    "description": "Synthetic financial activity",
                    "amount": f"{'-' if cents < 0 else ''}{abs(cents) // 100}.{abs(cents) % 100:02d}",
                    "currency": "EUR",
                    "category": category,
                    "source": "synthetic",
                }
                transactions.append(row)
                oracle["income" if cents > 0 else "spending"] += abs(cents)
                if kind == "refund":
                    oracle["refunds"] += cents
                    categories["Groceries"] -= cents
                elif kind == "expense":
                    categories[category] += abs(cents)
            oracle["net_cash_flow"] = oracle["income"] - oracle["spending"]
            oracle["net_spending"] = sum(categories.values())
            expected[f"{user_id}/{period}"] = {**oracle, "categories": dict(categories)}
    return {"seed": seed, "users": users, "transactions": transactions, "expected_cents": expected}


if __name__ == "__main__":
    print(json.dumps(generate_dataset(), sort_keys=True, indent=2))

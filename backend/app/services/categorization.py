from decimal import Decimal


class CategorizationService:
    RULES: tuple[tuple[str, str], ...] = (
        ("rent", "Housing"),
        ("mortgage", "Housing"),
        ("uber", "Transport"),
        ("lyft", "Transport"),
        ("shell", "Transport"),
        ("spotify", "Subscriptions"),
        ("netflix", "Subscriptions"),
        ("amazon", "Shopping"),
        ("whole foods", "Groceries"),
        ("trader joe", "Groceries"),
        ("salary", "Income"),
        ("payroll", "Income"),
    )

    def categorize(self, merchant: str, description: str, amount: Decimal) -> str:
        text = f"{merchant} {description}".lower()
        if amount > 0:
            return "Income"
        for needle, category in self.RULES:
            if needle in text:
                return category
        return "Uncategorized"

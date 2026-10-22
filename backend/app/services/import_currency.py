"""Explicit CSV currency resolution, independent of manual transaction defaults."""

from fastapi import HTTPException

from app.services.financial_context import SUPPORTED_CURRENCIES


def validate_import_currency(value: str, context: str) -> str:
    normalized = value.strip().upper()
    if normalized not in SUPPORTED_CURRENCIES:
        raise HTTPException(
            400,
            f"Invalid or unsupported currency in {context}. Choose one of "
            f"{', '.join(sorted(SUPPORTED_CURRENCIES))}; no currency conversion is performed.",
        )
    return normalized


class CsvCurrencyResolver:
    def __init__(self, headers: list[str] | None, import_currency: str | None):
        columns = [h for h in (headers or []) if h.strip().casefold() == "currency"]
        if len(columns) > 1:
            raise HTTPException(
                400, "Duplicate currency columns. Keep exactly one currency column."
            )
        self.column = columns[0] if columns else None
        self.selection = (
            validate_import_currency(import_currency, "import_currency selection")
            if import_currency is not None
            else None
        )

    def resolve(self, row: dict, line: int) -> str:
        value = row.get(self.column) if self.column is not None else None
        if value is None or not value.strip():
            if self.selection is not None:
                return self.selection
            raise HTTPException(
                400,
                f"Missing currency on CSV line {line}. Add a currency column with explicit codes "
                "or select the statement currency in the CSV currency selector "
                "(API: import_currency), then retry the entire import.",
            )
        currency = validate_import_currency(value, f"CSV line {line}")
        if self.selection is not None and currency != self.selection:
            raise HTTPException(
                400,
                f"Currency conflict on CSV line {line}: row currency {currency} does not match "
                f"import_currency {self.selection}. Correct the selection or use currency column "
                "mode for mixed-currency files; currencies are never converted.",
            )
        return currency

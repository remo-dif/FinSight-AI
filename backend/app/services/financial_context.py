"""Explicit reporting capabilities; never guess a different currency or period."""

import re
from datetime import UTC, date, datetime

SUPPORTED_CURRENCIES = frozenset({"EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD"})
_COMMON_UPPER_WORDS = {
    "THE",
    "AND",
    "FOR",
    "HOW",
    "CAN",
    "YOU",
    "ARE",
    "ANY",
    "ALL",
    "NET",
    "TOP",
    "CSV",
    "API",
    "NOT",
    "NEW",
    "GET",
    "SUM",
    "TAX",
    "PAY",
    "FEE",
}
_KNOWN_CODES = SUPPORTED_CURRENCIES | {
    "SEK",
    "NOK",
    "DKK",
    "PLN",
    "CNY",
    "INR",
    "BRL",
    "MXN",
    "ZAR",
    "SGD",
    "HKD",
    "AED",
    "NZD",
    "RUB",
    "BTC",
    "ETH",
}


def reporting_currency(value: str) -> str:
    value = value.upper()
    if value not in SUPPORTED_CURRENCIES:
        raise ValueError(
            f"Unsupported currency '{value}'. Choose one of {', '.join(sorted(SUPPORTED_CURRENCIES))}; currency conversion is not supported."
        )
    return value


def resolve_context(message: str, intent: str, currency: str | None = None) -> dict:
    candidates = set(re.findall(r"\b[A-Z]{3}\b", message)) - _COMMON_UPPER_WORDS
    candidates.update(
        re.findall(r"\b(?:" + "|".join(sorted(_KNOWN_CODES)) + r")\b", message.upper())
    )
    candidates.update(
        code.upper()
        for code in re.findall(
            r"\b(?:currency|in|using)(?:\s*[:=]\s*|\s+)([a-zA-Z]{3})\b", message, re.IGNORECASE
        )
        if code.upper() not in _COMMON_UPPER_WORDS | {"MAY", "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}
    )
    candidates.update(code.upper() for code in re.findall(r"\b([a-zA-Z]{3})\s+\d{4}-\d{2}\b", message)
                      if code.upper() not in _COMMON_UPPER_WORDS)
    for word, code in {"euros": "EUR", "euro": "EUR", "pounds": "GBP", "yen": "JPY"}.items():
        if re.search(r"\b" + word + r"\b", message, re.IGNORECASE):
            candidates.add(code)
    if "€" in message:
        candidates.add("EUR")
    if "$" in message or re.search(r"\bdollars?\b", message, re.IGNORECASE):
        raise ValueError(
            "Ambiguous currency request. Use an explicit code such as USD, CAD or AUD."
        )
    if currency:
        candidates.add(currency.upper())
    for candidate in candidates:
        reporting_currency(candidate)
    if len(candidates) > 1:
        raise ValueError(
            "Conflicting currencies. Select a single currency code; conversion is not supported."
        )
    selected_currency = next(iter(candidates), None)
    months = list(dict.fromkeys(re.findall(r"(?<!\d)\d{4}-\d{2}(?!\d)", message)))
    for month in months:
        try:
            start = date.fromisoformat(f"{month}-01")
            if start.year == 9999 and start.month == 12:
                raise ValueError("Unsupported upper boundary")
        except ValueError as exc:
            raise ValueError(
                "Invalid reporting month. Use a valid YYYY-MM, for example 2025-01."
            ) from exc
    remaining = re.sub(r"(?<!\d)\d{4}-\d{2}(?!\d)", "", message)
    unsupported = re.search(
        r"\b(?:last|previous|this|next|past|current)\s+(?:\d+\s+)?(?:months?|years?|weeks?|quarters?|days?)\b|\b(?:january|february|march|april|may(?!\s+i\b)|june|july|august|september|october|november|december|today|yesterday|quarter|weekly|daily|yearly|q[1-4]|ytd|mtd)\b",
        message,
        re.IGNORECASE,
    )
    if (
        unsupported
        or re.search(r"\b\d{4}-\d{2}-\d{2}\b", message)
        or re.search(r"\b\d{4}\b", remaining)
    ):
        raise ValueError(
            "Unsupported reporting period. Use YYYY-MM, or two YYYY-MM values for a supported comparison."
        )
    history = bool(re.search(r"\ball[ -]history\b", message, re.IGNORECASE))
    comparison = bool(re.search(r"compar|increas|decreas", message, re.IGNORECASE))
    if len(months) == 2 and not comparison and re.search(r"\b(?:from|through|between|until)\b", message, re.IGNORECASE):
        raise ValueError("Date ranges are unsupported. Use one YYYY-MM, or explicitly compare two YYYY-MM months.")
    if len(months) > 2:
        raise ValueError("Unsupported period: select at most two YYYY-MM values.")
    if history and months:
        raise ValueError(
            "Conflicting reporting periods. Choose all history or explicit YYYY-MM values."
        )
    if intent in {"budget", "recurring"} and (months or comparison):
        raise ValueError(
            f"{intent.title()} supports all history only. Remove the month or comparison scope."
        )
    if (len(months) == 2 or comparison) and intent not in {"summary", "category"}:
        raise ValueError(
            f"A {intent} comparison is unsupported. Request one YYYY-MM or all history."
        )
    if comparison and len(months) != 2:
        raise ValueError(
            "A comparison requires two distinct YYYY-MM values, for example 2025-01 and 2025-02."
        )
    if len(months) == 2:
        return {
            "intent": "summary",
            "months": months,
            "currency": selected_currency,
            "reporting_period": " to ".join(months),
            "month": None,
        }
    if history and intent in {"summary", "category"}:
        raise ValueError(
            "This report requires YYYY-MM. All history is unsupported for summary/category chat reports."
        )
    month = (
        months[0]
        if months
        else (datetime.now(UTC).strftime("%Y-%m") if intent in {"summary", "category"} else None)
    )
    return {
        "intent": intent,
        "months": months,
        "currency": selected_currency,
        "reporting_period": month or "all history",
        "month": month,
    }

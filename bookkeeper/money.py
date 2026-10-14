"""Money helpers.

All monetary amounts are stored and computed as integer cents. Decimal is used
at the edges (parsing user input, percentages, tax math) so that no binary
floating-point value ever reaches the ledger.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def to_cents(amount) -> int:
    """Convert a dollar amount (str / int / Decimal / float from a UI widget) to integer cents."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Not a valid amount: {amount!r}") from exc
    if not value.is_finite():
        raise ValueError(f"Not a valid amount: {amount!r}")
    return int((value.quantize(CENT, rounding=ROUND_HALF_UP) * 100).to_integral_value())


def to_decimal(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(CENT)


def round_cents(value: Decimal) -> int:
    """Round a Decimal number of cents half-up to an integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(cents: int) -> str:
    """$1,234.56 — negatives in accounting parentheses."""
    text = f"${abs(to_decimal(cents)):,.2f}"
    return f"({text})" if cents < 0 else text

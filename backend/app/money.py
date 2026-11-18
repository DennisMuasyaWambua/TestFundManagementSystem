"""Money and rate arithmetic.

Every monetary value in this system is a :class:`decimal.Decimal` quantised to two
decimal places; every rate is a ``Decimal`` quantised to eight.  Floats are never used
for money anywhere in the codebase -- see ``tests/test_no_floats.py`` which enforces it.

Rounding is ROUND_HALF_UP and happens only at the points named in the build spec:
the end of an accrual calculation, a currency conversion, and a fee calculation.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, getcontext
from typing import Final

# Plenty of headroom: NUMERIC(24,8) needs at most 24 significant digits.
getcontext().prec = 40

CENTS: Final = Decimal("0.01")
RATE_UNIT: Final = Decimal("0.00000001")
ZERO: Final = Decimal("0.00")

MONEY_SCALE: Final = 2
RATE_SCALE: Final = 8


class MoneyError(ValueError):
    """Raised when a value cannot be interpreted as money or a rate."""


def money(value: Decimal | int | str) -> Decimal:
    """Coerce *value* to a cent-quantised Decimal.

    Accepts ``Decimal``, ``int`` and ``str`` only.  ``float`` is rejected on purpose:
    accepting it would silently import binary rounding error into the ledger.
    """
    if isinstance(value, float):  # pragma: no cover - guarded by type checker too
        raise MoneyError("money() refuses float; pass Decimal or str")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ArithmeticError) as exc:
        raise MoneyError(f"not a valid amount: {value!r}") from exc
    if not dec.is_finite():
        raise MoneyError(f"not a finite amount: {value!r}")
    return dec.quantize(CENTS, rounding=ROUND_HALF_UP)


def rate(value: Decimal | int | str) -> Decimal:
    """Coerce *value* to an 8dp-quantised Decimal rate."""
    if isinstance(value, float):  # pragma: no cover
        raise MoneyError("rate() refuses float; pass Decimal or str")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ArithmeticError) as exc:
        raise MoneyError(f"not a valid rate: {value!r}") from exc
    if not dec.is_finite():
        raise MoneyError(f"not a finite rate: {value!r}")
    return dec.quantize(RATE_UNIT, rounding=ROUND_HALF_UP)


def round_money(value: Decimal) -> Decimal:
    """Round an unquantised intermediate result to cents, half-up."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def convert(amount: Decimal, fx_rate: Decimal) -> Decimal:
    """Convert *amount* to base currency at *fx_rate* (base units per 1 unit)."""
    return round_money(amount * fx_rate)


def total(amounts: Sequence[Decimal]) -> Decimal:
    """Sum a sequence of cent amounts without intermediate rounding."""
    acc = Decimal(0)
    for a in amounts:
        acc += a
    return round_money(acc)


def fmt(amount: Decimal) -> str:
    """Render money the way it travels over the API: a plain 2dp string."""
    return f"{money(amount):.2f}"


def fmt_rate(value: Decimal) -> str:
    """Render a rate the way it travels over the API: trailing zeros trimmed."""
    text = f"{rate(value):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def split_pro_rata(amount: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Split *amount* across *weights* so the parts add back to *amount* exactly.

    Uses the largest-remainder method: each part is floored to cents, then the
    leftover cents are handed out one at a time to the largest remainders.  Used for
    the pro-rata accrued-profit placeholder in the opening balance migration.
    """
    if not weights:
        raise MoneyError("split_pro_rata needs at least one weight")
    if any(w < 0 for w in weights):
        raise MoneyError("split_pro_rata weights must not be negative")
    weight_sum = sum(weights, Decimal(0))
    if weight_sum == 0:
        raise MoneyError("split_pro_rata weights must not all be zero")

    exact = [amount * w / weight_sum for w in weights]
    floored = [e.quantize(CENTS, rounding="ROUND_DOWN") for e in exact]
    shortfall = int(((amount - sum(floored, Decimal(0))) / CENTS).to_integral_value())
    order = sorted(range(len(weights)), key=lambda i: exact[i] - floored[i], reverse=True)
    for n in range(shortfall):
        floored[order[n % len(order)]] += CENTS
    return floored

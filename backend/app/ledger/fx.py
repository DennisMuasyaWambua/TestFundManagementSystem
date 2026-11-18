"""FX rate lookup.

A rate is the number of base currency units per one unit of the foreign currency.
The rate used for a posting is the latest rate on or before the posting date; a
missing rate is a hard error that names the currency and the date, never a guess.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import MissingFxRate
from app.models import FxRate

ONE = Decimal("1.00000000")


def rate_for(db: Session, currency: str, base_currency: str, on: date) -> Decimal:
    """The rate to use when posting *currency* into *base_currency* books on *on*."""
    if currency == base_currency:
        return ONE
    found = db.execute(
        select(FxRate.rate)
        .where(
            FxRate.currency == currency,
            FxRate.base_currency == base_currency,
            FxRate.rate_date <= on,
        )
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if found is None:
        raise MissingFxRate(
            f"no {currency}/{base_currency} rate on or before {on.isoformat()}",
            currency=currency,
            base_currency=base_currency,
            rate_date=on.isoformat(),
        )
    return found


def exact_rate_for(db: Session, currency: str, base_currency: str, on: date) -> Decimal | None:
    """The rate entered for exactly *on*, or None.  Used by the month-end close."""
    if currency == base_currency:
        return ONE
    return db.execute(
        select(FxRate.rate).where(
            FxRate.currency == currency,
            FxRate.base_currency == base_currency,
            FxRate.rate_date == on,
        )
    ).scalar_one_or_none()

"""Shared schema types.

Money and rates travel over the API as strings -- ``"1000000.00"``, ``"0.0425"`` --
never as JSON numbers, so no client can turn them into a float by accident.  Inside
the API they are ``Decimal`` the whole way.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer, WithJsonSchema

from app.money import fmt, fmt_rate, money, rate


def _parse_money(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send money as a string, not a JSON number")
    if isinstance(value, str):
        try:
            return money(Decimal(value.strip()))
        except (InvalidOperation, ArithmeticError) as exc:
            raise ValueError(f"not a valid amount: {value!r}") from exc
    if isinstance(value, Decimal | int):
        return money(value)
    return value


def _parse_rate(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send rates as a string, not a JSON number")
    if isinstance(value, str):
        try:
            return rate(Decimal(value.strip()))
        except (InvalidOperation, ArithmeticError) as exc:
            raise ValueError(f"not a valid rate: {value!r}") from exc
    if isinstance(value, Decimal | int):
        return rate(value)
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(_parse_money),
    PlainSerializer(fmt, return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["1000000.00"]}),
]

Rate = Annotated[
    Decimal,
    BeforeValidator(_parse_rate),
    PlainSerializer(fmt_rate, return_type=str),
    WithJsonSchema({"type": "string", "examples": ["0.0425"]}),
]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")


class Page[T](Schema):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(Schema):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(Schema):
    error: ErrorBody


class Ok(Schema):
    ok: bool = True
    message: str = ""


class AuditEntry(Schema):
    id: int
    at: datetime
    user_id: str
    action: str
    entity: str
    entity_id: str | None = None
    client_id: str | None = None
    detail: dict[str, Any] = {}
    ip: str | None = None


class DateRange(Schema):
    from_date: date
    to_date: date

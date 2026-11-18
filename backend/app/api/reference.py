"""Reference data: the chart of accounts, role mappings and FX rates."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, needs
from app.models import Account, FxRate, User
from app.schemas.models import AccountRow, CreateFxRateRequest, FxRateRow, RoleMappingRow
from app.services import clients as clients_svc
from app.services import fx as fx_svc
from app.services.permissions import Permission

router = APIRouter(tags=["reference"])


@router.get("/accounts", response_model=list[AccountRow])
def list_accounts(
    db: DbSession,
    _: CurrentUser,
    postable_only: bool = False,
) -> list[AccountRow]:
    stmt = select(Account).order_by(Account.code)
    if postable_only:
        stmt = stmt.where(Account.is_postable.is_(True))
    return [AccountRow.model_validate(row) for row in db.execute(stmt).scalars()]


@router.get("/role-mappings", response_model=list[RoleMappingRow])
def list_role_mappings(
    db: DbSession, _: CurrentUser, client: str | None = None
) -> list[RoleMappingRow]:
    return [RoleMappingRow.model_validate(row) for row in clients_svc.role_mappings(db, client)]


@router.get("/fx-rates", response_model=list[FxRateRow])
def list_fx_rates(
    db: DbSession,
    _: CurrentUser,
    currency: str | None = None,
    base: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=200, le=1000),
) -> list[FxRateRow]:
    stmt = select(FxRate).order_by(FxRate.rate_date.desc(), FxRate.currency)
    if currency:
        stmt = stmt.where(FxRate.currency == currency.upper())
    if base:
        stmt = stmt.where(FxRate.base_currency == base.upper())
    if from_date:
        stmt = stmt.where(FxRate.rate_date >= from_date)
    if to_date:
        stmt = stmt.where(FxRate.rate_date <= to_date)
    return [FxRateRow.model_validate(row) for row in db.execute(stmt.limit(limit)).scalars()]


@router.get("/fx-rates/latest", response_model=FxRateRow)
def latest_fx_rate(
    db: DbSession,
    _: CurrentUser,
    currency: str,
    base: str,
    on: date | None = None,
) -> FxRateRow:
    from app.errors import MissingFxRate

    as_of = on or date.today()
    row = db.execute(
        select(FxRate)
        .where(
            FxRate.currency == currency.upper(),
            FxRate.base_currency == base.upper(),
            FxRate.rate_date <= as_of,
        )
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise MissingFxRate(
            f"no {currency.upper()}/{base.upper()} rate on or before {as_of.isoformat()}",
            currency=currency.upper(),
            base_currency=base.upper(),
        )
    return FxRateRow.model_validate(row)


@router.post("/fx-rates", response_model=FxRateRow, status_code=201)
def create_fx_rate(
    body: CreateFxRateRequest,
    db: DbSession,
    actor: User = needs(Permission.FX_RATES_MANAGE),
) -> FxRateRow:
    row = fx_svc.record_rate(
        db,
        currency=body.currency.upper(),
        base_currency=body.base_currency.upper(),
        rate_date=body.rate_date,
        value=body.rate,
        source=body.source,
        entered_by=actor.id,
    )
    return FxRateRow.model_validate(row)

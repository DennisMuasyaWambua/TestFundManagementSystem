"""Reporting endpoints, including the client statement and its PDF."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentUser, DbSession, guard_client, needs
from app.models import User
from app.schemas.models import (
    BalanceSheetResponse,
    DashboardResponse,
    PortfolioSummaryResponse,
    ProfitAndLossResponse,
    StatementResponse,
    TrialBalanceResponse,
)
from app.services import reports as reports_svc
from app.services import statements as statements_svc
from app.services.permissions import Permission

router = APIRouter(tags=["reports"])
VIEW = needs(Permission.REPORTS_VIEW)


@router.get("/reports/trial-balance", response_model=TrialBalanceResponse)
def trial_balance(
    db: DbSession, as_of: date, client: str | None = None, user: User = VIEW
) -> TrialBalanceResponse:
    if client:
        guard_client(db, user, client)
    result = reports_svc.trial_balance(db, as_of=as_of, client_id=client)
    return TrialBalanceResponse(
        as_of=result.as_of,
        client_id=result.client_id,
        rows=[
            {
                "code": row.code,
                "name": row.name,
                "type": row.type,
                "debit": row.debit,
                "credit": row.credit,
            }
            for row in result.rows
        ],
        total_debit=result.total_debit,
        total_credit=result.total_credit,
        balanced=result.balanced,
    )


@router.get("/clients/{client_id}/balance-sheet", response_model=BalanceSheetResponse)
def balance_sheet(
    client_id: str, db: DbSession, as_of: date, user: User = VIEW
) -> BalanceSheetResponse:
    guard_client(db, user, client_id)
    result = reports_svc.balance_sheet(db, client_id, as_of=as_of)
    return BalanceSheetResponse.model_validate(result, from_attributes=True)


@router.get("/clients/{client_id}/profit-and-loss", response_model=ProfitAndLossResponse)
def profit_and_loss(
    client_id: str,
    db: DbSession,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    user: User = VIEW,
) -> ProfitAndLossResponse:
    guard_client(db, user, client_id)
    result = reports_svc.profit_and_loss(db, client_id, from_date=from_date, to_date=to_date)
    return ProfitAndLossResponse.model_validate(
        {
            "client_id": result.client_id,
            "client": result.client,
            "currency": result.currency,
            "from_date": result.from_date,
            "to_date": result.to_date,
            "income": result.income,
            "expenses": result.expenses,
            "net_profit": result.net_profit,
        },
        from_attributes=True,
    )


@router.get("/clients/{client_id}/statement", response_model=StatementResponse)
def statement(
    client_id: str,
    db: DbSession,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    user: User = VIEW,
) -> StatementResponse:
    guard_client(db, user, client_id)
    from app.services import audit

    result = reports_svc.client_statement(db, client_id, from_date=from_date, to_date=to_date)
    audit.record(
        db,
        user_id=user.id,
        action="STATEMENT_VIEWED",
        entity="client",
        entity_id=client_id,
        client_id=client_id,
        detail={"from": from_date.isoformat(), "to": to_date.isoformat()},
    )
    return StatementResponse.model_validate(result, from_attributes=True)


@router.get("/clients/{client_id}/statement.pdf")
def statement_pdf(
    client_id: str,
    db: DbSession,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    user: User = VIEW,
) -> Response:
    guard_client(db, user, client_id)
    from app.services import audit

    built = statements_svc.render(db, client_id, from_date=from_date, to_date=to_date)
    audit.record(
        db,
        user_id=user.id,
        action="STATEMENT_DOWNLOADED",
        entity="client",
        entity_id=client_id,
        client_id=client_id,
        detail={
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "sha256": built.sha256,
        },
    )
    return Response(
        content=built.pdf,
        media_type="application/pdf",
        headers={
            "content-disposition": f'inline; filename="{built.filename}"',
            "x-statement-sha256": built.sha256,
        },
    )


@router.get("/reports/portfolio-summary", response_model=PortfolioSummaryResponse)
def portfolio_summary(
    db: DbSession, as_of: date, client: str | None = None, user: User = VIEW
) -> PortfolioSummaryResponse:
    if client:
        guard_client(db, user, client)
    result = reports_svc.portfolio_summary(db, as_of=as_of, client_id=client)
    return PortfolioSummaryResponse.model_validate(result, from_attributes=True)


@router.get("/reports/portfolio-summary.xlsx")
def portfolio_summary_xlsx(
    db: DbSession, as_of: date, client: str | None = None, user: User = VIEW
) -> Response:
    if client:
        guard_client(db, user, client)
    content = statements_svc.portfolio_summary_xlsx(db, as_of=as_of, client_id=client)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "content-disposition": (
                f'attachment; filename="portfolio-summary-{as_of.isoformat()}.xlsx"'
            )
        },
    )


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(db: DbSession, user: CurrentUser, as_of: date | None = None) -> DashboardResponse:
    result = reports_svc.dashboard(db, as_of=as_of or date.today(), user_id=user.id)
    return DashboardResponse.model_validate(result, from_attributes=True)

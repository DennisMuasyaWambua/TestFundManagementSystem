"""Client onboarding endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, guard_client, needs
from app.models import Client, User
from app.schemas.models import (
    ClientRow,
    CreateClientRequest,
    CreateCustodyAccountRequest,
    CustodyAccountRow,
    KycRequest,
    MandateFeeRow,
    SetMandateFeesRequest,
    UpdateClientRequest,
)
from app.services import auth as auth_svc
from app.services import clients as clients_svc
from app.services.permissions import Permission

router = APIRouter(tags=["clients"])
ONBOARDING = needs(Permission.CLIENT_ONBOARDING)


def _row(client: Client) -> ClientRow:
    return ClientRow.model_validate(client)


@router.get("/clients", response_model=list[ClientRow])
def list_clients(db: DbSession, user: CurrentUser) -> list[ClientRow]:
    allowed = auth_svc.accessible_clients(db, user)
    return [_row(client) for client in clients_svc.list_clients(db, allowed=allowed)]


@router.get("/clients/{client_id}", response_model=ClientRow)
def get_client(client_id: str, db: DbSession, user: CurrentUser) -> ClientRow:
    guard_client(db, user, client_id)
    return _row(clients_svc.get(db, client_id))


@router.post("/clients", response_model=ClientRow, status_code=201)
def create_client(body: CreateClientRequest, db: DbSession, actor: User = ONBOARDING) -> ClientRow:
    client = clients_svc.create(
        db,
        client_id=body.id,
        legal_name=body.legal_name,
        base_currency=body.base_currency,
        actor_id=actor.id,
        agreement_ref=body.agreement_ref,
        agreement_date=body.agreement_date,
        final_wht_rate=body.final_wht_rate,
    )
    return _row(client)


@router.patch("/clients/{client_id}", response_model=ClientRow)
def update_client(
    client_id: str,
    body: UpdateClientRequest,
    db: DbSession,
    actor: User = ONBOARDING,
) -> ClientRow:
    guard_client(db, actor, client_id)
    client = clients_svc.update(
        db,
        client_id,
        actor_id=actor.id,
        legal_name=body.legal_name,
        agreement_ref=body.agreement_ref,
        agreement_date=body.agreement_date,
        final_wht_rate=body.final_wht_rate,
        status=body.status,
    )
    return _row(client)


@router.post("/clients/{client_id}/kyc", response_model=ClientRow)
def record_kyc(
    client_id: str, body: KycRequest, db: DbSession, actor: User = ONBOARDING
) -> ClientRow:
    guard_client(db, actor, client_id)
    client = clients_svc.record_kyc(
        db,
        client_id,
        actor_id=actor.id,
        kyc_status=body.kyc_status,
        aml_risk_rating=body.aml_risk_rating,
        reviewed_on=body.reviewed_on,
        note=body.note,
    )
    return _row(client)


@router.get("/clients/{client_id}/custody-accounts", response_model=list[CustodyAccountRow])
def list_custody_accounts(
    client_id: str, db: DbSession, user: CurrentUser
) -> list[CustodyAccountRow]:
    guard_client(db, user, client_id)
    return [
        CustodyAccountRow.model_validate(row) for row in clients_svc.custody_accounts(db, client_id)
    ]


@router.post(
    "/clients/{client_id}/custody-accounts", response_model=CustodyAccountRow, status_code=201
)
def add_custody_account(
    client_id: str,
    body: CreateCustodyAccountRequest,
    db: DbSession,
    actor: User = ONBOARDING,
) -> CustodyAccountRow:
    guard_client(db, actor, client_id)
    row = clients_svc.add_custody_account(
        db,
        client_id,
        actor_id=actor.id,
        account_id=body.id,
        custodian=body.custodian,
        account_number=body.account_number,
        currency=body.currency,
        cash_ledger_code=body.cash_ledger_code,
        wakala_ledger_code=body.wakala_ledger_code,
        custodian_address=body.custodian_address,
        custodian_contact=body.custodian_contact,
        custody_agreement_ref=body.custody_agreement_ref,
        is_default=body.is_default,
    )
    return CustodyAccountRow.model_validate(row)


@router.get("/clients/{client_id}/fees", response_model=list[MandateFeeRow])
def list_fees(client_id: str, db: DbSession, user: CurrentUser) -> list[MandateFeeRow]:
    guard_client(db, user, client_id)
    return [MandateFeeRow.model_validate(row) for row in clients_svc.fees(db, client_id)]


@router.put("/clients/{client_id}/fees", response_model=list[MandateFeeRow])
def set_fees(
    client_id: str,
    body: SetMandateFeesRequest,
    db: DbSession,
    actor: User = ONBOARDING,
) -> list[MandateFeeRow]:
    guard_client(db, actor, client_id)
    rows = clients_svc.set_fees(
        db,
        client_id,
        actor_id=actor.id,
        rows=[(fee.asset_class, fee.fee_pct_of_income, fee.effective_from) for fee in body.fees],
    )
    return [MandateFeeRow.model_validate(row) for row in rows]

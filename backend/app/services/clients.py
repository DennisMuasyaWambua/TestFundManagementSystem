"""Client onboarding: the mandate, its KYC, its custody accounts and its fee rates.

Nothing can be instructed on until the gate is complete: KYC approved, an investment
management agreement reference on file, and a custody account with its custody
appointment reference.  That gate is the system's expression of CoB regs 4 and 13 and
Licensing Regs 2025 reg 42(1)(d).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import BusinessRule, Conflict, NotFound
from app.models import (
    Account,
    AssetClass,
    Client,
    CustodyAccount,
    KycStatus,
    MandateFee,
    RecordStatus,
    RiskRating,
    RoleMapping,
)
from app.services import audit


def get(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    return client


def list_clients(db: Session, *, allowed: list[str] | None = None) -> list[Client]:
    stmt = select(Client).order_by(Client.legal_name)
    if allowed is not None:
        stmt = stmt.where(Client.id.in_(allowed))
    return list(db.execute(stmt).scalars())


def create(
    db: Session,
    *,
    client_id: str,
    legal_name: str,
    base_currency: str,
    actor_id: str,
    agreement_ref: str | None = None,
    agreement_date: date | None = None,
    final_wht_rate: Decimal | None = None,
) -> Client:
    if db.get(Client, client_id) is not None:
        raise Conflict(f"client {client_id} already exists", client_id=client_id)
    client = Client(
        id=client_id,
        legal_name=legal_name,
        base_currency=base_currency.upper(),
        kyc_status=KycStatus.PENDING,
        agreement_ref=agreement_ref,
        agreement_date=agreement_date,
        final_wht_rate=(
            final_wht_rate if final_wht_rate is not None else get_settings().default_final_wht_rate
        ),
        created_by=actor_id,
    )
    db.add(client)
    db.flush()
    audit.record(
        db,
        user_id=actor_id,
        action="CLIENT_CREATED",
        entity="client",
        entity_id=client_id,
        client_id=client_id,
        detail={"legal_name": legal_name, "base_currency": base_currency},
    )
    return client


def update(
    db: Session,
    client_id: str,
    *,
    actor_id: str,
    legal_name: str | None = None,
    agreement_ref: str | None = None,
    agreement_date: date | None = None,
    final_wht_rate: Decimal | None = None,
    status: RecordStatus | None = None,
) -> Client:
    client = get(db, client_id)
    before = {
        "legal_name": client.legal_name,
        "agreement_ref": client.agreement_ref,
        "agreement_date": None
        if client.agreement_date is None
        else client.agreement_date.isoformat(),
        "final_wht_rate": f"{client.final_wht_rate:f}",
        "status": str(client.status),
    }
    if legal_name is not None:
        client.legal_name = legal_name
    if agreement_ref is not None:
        client.agreement_ref = agreement_ref
    if agreement_date is not None:
        client.agreement_date = agreement_date
    if final_wht_rate is not None:
        client.final_wht_rate = final_wht_rate
    if status is not None:
        client.status = status
    client.updated_by = actor_id
    db.flush()
    audit.record(
        db,
        user_id=actor_id,
        action="CLIENT_UPDATED",
        entity="client",
        entity_id=client_id,
        client_id=client_id,
        detail={
            "before": before,
            "after": {
                "legal_name": client.legal_name,
                "agreement_ref": client.agreement_ref,
                "agreement_date": None
                if client.agreement_date is None
                else client.agreement_date.isoformat(),
                "final_wht_rate": f"{client.final_wht_rate:f}",
                "status": str(client.status),
            },
        },
    )
    return client


def record_kyc(
    db: Session,
    client_id: str,
    *,
    actor_id: str,
    kyc_status: KycStatus,
    aml_risk_rating: RiskRating | None = None,
    reviewed_on: date | None = None,
    note: str = "",
) -> Client:
    client = get(db, client_id)
    before = {"kyc_status": str(client.kyc_status), "aml_risk_rating": str(client.aml_risk_rating)}
    client.kyc_status = kyc_status
    if aml_risk_rating is not None:
        client.aml_risk_rating = aml_risk_rating
    client.kyc_reviewed_on = reviewed_on or date.today()
    client.updated_by = actor_id
    db.flush()
    audit.record(
        db,
        user_id=actor_id,
        action="CLIENT_KYC_RECORDED",
        entity="client",
        entity_id=client_id,
        client_id=client_id,
        detail={
            "before": before,
            "after": {
                "kyc_status": str(kyc_status),
                "aml_risk_rating": str(client.aml_risk_rating),
            },
            "note": note,
        },
    )
    return client


def custody_accounts(db: Session, client_id: str) -> list[CustodyAccount]:
    return list(
        db.execute(
            select(CustodyAccount)
            .where(CustodyAccount.client_id == client_id)
            .order_by(CustodyAccount.id)
        ).scalars()
    )


def add_custody_account(
    db: Session,
    client_id: str,
    *,
    actor_id: str,
    account_id: str,
    custodian: str,
    account_number: str,
    currency: str,
    cash_ledger_code: str,
    wakala_ledger_code: str,
    custodian_address: str = "",
    custodian_contact: str = "The Custody Manager",
    custody_agreement_ref: str | None = None,
    is_default: bool = False,
) -> CustodyAccount:
    get(db, client_id)
    if db.get(CustodyAccount, account_id) is not None:
        raise Conflict(f"custody account {account_id} already exists", id=account_id)
    for code in (cash_ledger_code, wakala_ledger_code):
        account = db.get(Account, code)
        if account is None:
            raise NotFound(f"unknown account {code}", account_code=code)
        if not account.is_postable:
            raise BusinessRule(f"account {code} is a heading and cannot hold a balance")
        if account.currency and account.currency != currency.upper():
            raise BusinessRule(
                f"account {code} is a {account.currency} account but the custody account is "
                f"{currency.upper()}"
            )
    row = CustodyAccount(
        id=account_id,
        client_id=client_id,
        custodian=custodian,
        custodian_address=custodian_address,
        custodian_contact=custodian_contact,
        account_number=account_number,
        currency=currency.upper(),
        cash_ledger_code=cash_ledger_code,
        wakala_ledger_code=wakala_ledger_code,
        custody_agreement_ref=custody_agreement_ref,
        is_default=is_default,
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        user_id=actor_id,
        action="CUSTODY_ACCOUNT_ADDED",
        entity="custody_account",
        entity_id=account_id,
        client_id=client_id,
        detail={
            "custodian": custodian,
            "account_number": account_number,
            "currency": currency.upper(),
            "custody_agreement_ref": custody_agreement_ref,
        },
    )
    return row


def fees(db: Session, client_id: str) -> list[MandateFee]:
    return list(
        db.execute(
            select(MandateFee)
            .where(MandateFee.client_id == client_id)
            .order_by(MandateFee.asset_class, MandateFee.effective_from.desc())
        ).scalars()
    )


def set_fees(
    db: Session,
    client_id: str,
    *,
    actor_id: str,
    rows: list[tuple[AssetClass, Decimal, date]],
) -> list[MandateFee]:
    get(db, client_id)
    for asset_class, pct, effective_from in rows:
        if pct < 0 or pct > 1:
            raise BusinessRule(
                "a management fee is a fraction of income between 0 and 1",
                asset_class=str(asset_class),
                value=str(pct),
            )
        existing = db.execute(
            select(MandateFee).where(
                MandateFee.client_id == client_id,
                MandateFee.asset_class == asset_class,
                MandateFee.effective_from == effective_from,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.fee_pct_of_income = pct
            existing.updated_by = actor_id
        else:
            db.add(
                MandateFee(
                    client_id=client_id,
                    asset_class=asset_class,
                    fee_pct_of_income=pct,
                    effective_from=effective_from,
                    created_by=actor_id,
                )
            )
    db.flush()
    audit.record(
        db,
        user_id=actor_id,
        action="MANDATE_FEES_SET",
        entity="client",
        entity_id=client_id,
        client_id=client_id,
        detail={
            "fees": [
                {
                    "asset_class": str(asset_class),
                    "pct": f"{pct:f}",
                    "effective_from": effective_from.isoformat(),
                }
                for asset_class, pct, effective_from in rows
            ]
        },
    )
    return fees(db, client_id)


def role_mappings(db: Session, client_id: str | None = None) -> list[RoleMapping]:
    stmt = select(RoleMapping).order_by(RoleMapping.client_id, RoleMapping.role)
    if client_id:
        stmt = stmt.where(RoleMapping.client_id.in_([client_id, "*"]))
    return list(db.execute(stmt).scalars())


def set_role_mapping(
    db: Session, *, client_id: str, role: str, account_code: str, actor_id: str
) -> RoleMapping:
    if db.get(Account, account_code) is None:
        raise NotFound(f"unknown account {account_code}", account_code=account_code)
    existing = db.execute(
        select(RoleMapping).where(RoleMapping.client_id == client_id, RoleMapping.role == role)
    ).scalar_one_or_none()
    if existing is None:
        existing = RoleMapping(client_id=client_id, role=role, created_by=actor_id)
        db.add(existing)
    before = existing.account_code if existing.id else None
    existing.account_code = account_code
    existing.updated_by = actor_id
    db.flush()
    audit.record(
        db,
        user_id=actor_id,
        action="ROLE_MAPPING_SET",
        entity="role_mapping",
        entity_id=existing.id,
        client_id=None if client_id == "*" else client_id,
        detail={"role": role, "before": before, "after": account_code},
    )
    return existing

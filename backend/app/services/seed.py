"""Seed data: the chart of accounts, the role mapping, users and the two go-live clients.

The chart of accounts and the role mapping come from CSV files under ``seed/`` -- the
files finance owns.  Everything derived from a code (whether it is a heading, its
normal balance, which report it belongs on) is computed here rather than keyed twice.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    NORMAL_BALANCE_BY_TYPE,
    REPORT_BY_TYPE,
    SYSTEM_USER,
    Account,
    AccountType,
    AssetClass,
    Client,
    CustodyAccount,
    KycStatus,
    MandateFee,
    RecordStatus,
    RoleMapping,
    User,
    UserRole,
)
from app.services import auth

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"

PLACEHOLDER = "<PLACEHOLDER - TO BE SUPPLIED>"


def is_heading(code: str) -> bool:
    """Codes ending in 00 are headings and are never posted to."""
    return code.endswith("00")


def parent_code(code: str) -> str | None:
    if code.endswith("000"):
        return None
    if code.endswith("00"):
        return code[0] + "000"
    return code[:2] + "00"


def load_chart_of_accounts(
    db: Session, *, path: Path | None = None, actor: str = SYSTEM_USER
) -> int:
    """Import finance's chart.  Re-runnable: existing rows are updated in place."""
    source = path or SEED_DIR / "chart_of_accounts.csv"
    loaded = 0
    with source.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            code = row["Code"].strip()
            if not code:
                continue
            acc_type = AccountType(row["Type"].strip())
            raw_status = row["Status"].strip().upper()
            account = db.get(Account, code) or Account(code=code, created_by=actor)
            account.name = row["Account"].strip()
            account.type = acc_type
            account.parent_code = parent_code(code)
            account.is_postable = not is_heading(code)
            account.normal_balance = NORMAL_BALANCE_BY_TYPE[acc_type]
            account.report = REPORT_BY_TYPE[acc_type]
            account.sub_ledger = row["Sub-ledger"].strip() or None
            account.needs_holding = account.sub_ledger == "HOLDING"
            account.currency = row["Currency"].strip() or None
            account.is_proposed = raw_status == "PROPOSED"
            account.status = (
                RecordStatus.ACTIVE
                if raw_status in {"ACTIVE", "PROPOSED"}
                else RecordStatus(raw_status)
            )
            account.updated_by = actor
            db.add(account)
            loaded += 1
    db.flush()
    return loaded


def load_role_mappings(db: Session, *, path: Path | None = None, actor: str = SYSTEM_USER) -> int:
    source = path or SEED_DIR / "roles.csv"
    loaded = 0
    with source.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            client_id = row["client_id"].strip()
            role = row["role"].strip()
            existing = db.execute(
                select(RoleMapping).where(
                    RoleMapping.client_id == client_id, RoleMapping.role == role
                )
            ).scalar_one_or_none()
            mapping = existing or RoleMapping(client_id=client_id, role=role, created_by=actor)
            mapping.account_code = row["account_code"].strip()
            mapping.updated_by = actor
            db.add(mapping)
            loaded += 1
    db.flush()
    return loaded


# --- Users -------------------------------------------------------------------

STARTER_USERS: tuple[tuple[str, str, str, UserRole], ...] = (
    ("ops.maker", "<OPERATIONS OFFICER>", "Operations Officer", UserRole.MAKER),
    ("sig.one", "<AUTHORISED SIGNATORY 1>", "Director", UserRole.SIGNATORY),
    ("sig.two", "<AUTHORISED SIGNATORY 2>", "Chief Executive Officer", UserRole.SIGNATORY),
    ("fin.head", "<HEAD OF FINANCE>", "Head of Finance", UserRole.FINANCE),
    ("fin.officer", "<FINANCE OFFICER>", "Finance Officer", UserRole.FINANCE),
    ("compliance", "<COMPLIANCE OFFICER>", "Compliance Officer", UserRole.COMPLIANCE),
    ("admin", "<SYSTEM ADMINISTRATOR>", "IT Administrator", UserRole.ADMIN),
)


def seed_users(db: Session, *, temporary: str | None = None) -> dict[str, str]:
    """Create the starter accounts.  Returns the temporary password per user id.

    Names and titles are placeholders (open decision 13); the specimen signatory names
    printed on instruction letters must be confirmed before go-live.
    """
    passwords: dict[str, str] = {}

    system = db.get(User, SYSTEM_USER)
    if system is None:
        db.add(
            User(
                id=SYSTEM_USER,
                name="Scheduled jobs",
                title="Service account",
                email="system@localhost",
                role=UserRole.FINANCE,
                active=True,
                can_login=False,
                password_hash="",
                must_change_password=False,
                created_by=SYSTEM_USER,
            )
        )

    for user_id, name, title, role in STARTER_USERS:
        if db.get(User, user_id) is not None:
            continue
        raw = temporary or auth.temporary_password()
        passwords[user_id] = raw
        db.add(
            User(
                id=user_id,
                name=name,
                title=title,
                email=f"{user_id}@example.invalid",
                role=role,
                active=True,
                can_login=True,
                password_hash=auth.hash_password(raw),
                must_change_password=True,
                created_by=SYSTEM_USER,
            )
        )
    db.flush()
    return passwords


# --- The two go-live mandates ------------------------------------------------


def seed_clients(db: Session, *, actor: str = SYSTEM_USER) -> None:
    """The two segregated mandates live at cutover, with their custody accounts.

    Agreement and custody appointment references are placeholders: the real document
    references must be keyed in before any instruction can be raised, which is exactly
    what the onboarding gate in ``services.clients`` enforces.
    """
    settings = get_settings()
    fee = settings.default_management_fee_pct

    mandates = (
        {
            "id": "RAYAN",
            "legal_name": "Rayan Realstate Development Sarl",
            "custody": (
                ("CR0012A", "Absa Bank Kenya PLC", "CR0012A", "USD", "1140", "1220", True),
                ("CR0012A-KES", "Absa Bank Kenya PLC", "CR0012A-KES", "KES", "1130", "1220", False),
            ),
        },
        {
            "id": "TAAJ",
            "legal_name": "Taaj Financial Services",
            "custody": (
                ("BOA-USD", "Bank of Africa Kenya", "BOA-CUSTODY-USD", "USD", "1120", "1210", True),
                (
                    "BOA-KES",
                    "Bank of Africa Kenya",
                    "BOA-CUSTODY-KES",
                    "KES",
                    "1110",
                    "1210",
                    False,
                ),
            ),
        },
    )

    for mandate in mandates:
        client_id = str(mandate["id"])
        client = db.get(Client, client_id)
        if client is None:
            client = Client(
                id=client_id,
                legal_name=str(mandate["legal_name"]),
                base_currency="USD",
                kyc_status=KycStatus.APPROVED,
                kyc_reviewed_on=date(2026, 1, 31),
                aml_risk_rating=None,
                agreement_ref=f"IMA/{client_id}/{PLACEHOLDER}",
                agreement_date=None,
                final_wht_rate=settings.default_final_wht_rate,
                created_by=actor,
            )
            db.add(client)

        for acc_id, custodian, number, currency, cash, wakala, default in mandate["custody"]:
            if db.get(CustodyAccount, acc_id) is not None:
                continue
            db.add(
                CustodyAccount(
                    id=acc_id,
                    client_id=client_id,
                    custodian=custodian,
                    custodian_address=PLACEHOLDER,
                    account_number=number,
                    currency=currency,
                    cash_ledger_code=cash,
                    wakala_ledger_code=wakala,
                    custody_agreement_ref=f"CUSTODY/{client_id}/{PLACEHOLDER}",
                    is_default=default,
                    created_by=actor,
                )
            )

        for asset_class in AssetClass:
            existing = db.execute(
                select(MandateFee).where(
                    MandateFee.client_id == client_id, MandateFee.asset_class == asset_class
                )
            ).first()
            if existing is None:
                db.add(
                    MandateFee(
                        client_id=client_id,
                        asset_class=asset_class,
                        fee_pct_of_income=Decimal(fee),
                        effective_from=date(2026, 1, 1),
                        created_by=actor,
                    )
                )
    db.flush()


def seed_all(db: Session, *, temporary_password: str | None = None) -> dict[str, str]:
    load_chart_of_accounts(db)
    load_role_mappings(db)
    passwords = seed_users(db, temporary=temporary_password)
    seed_clients(db)
    return passwords

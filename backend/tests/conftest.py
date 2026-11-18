"""Test fixtures.

The suite runs against SQLite with the same append-only triggers the production
PostgreSQL database gets, and with money stored as scaled integers so ``SUM()`` is
exact.  ``tests/test_migrations.py`` checks that the Alembic migration produces the
same schema, and CI additionally runs the whole suite against PostgreSQL 16.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

os.environ.setdefault("FMS_SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")
os.environ.setdefault("FMS_ENV", "ci")

from app import db as db_module
from app.config import get_settings, reset_settings_cache
from app.db import Base, install_append_only, make_engine
from app.ledger import posting
from app.models import Client, CustodyAccount, FxRate, KycStatus, MandateFee
from app.services import seed

TEST_PASSWORD = "Fms-Test-Pass-2026!"


@pytest.fixture(scope="session", autouse=True)
def _settings(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    store = tmp_path_factory.mktemp("filestore")
    os.environ["FMS_FILE_STORE_PATH"] = str(store)
    os.environ["FMS_DATABASE_URL"] = "sqlite://"
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite+pysqlite:///{(tmp_path / 'fms.sqlite').as_posix()}"
    eng = make_engine(url)
    Base.metadata.create_all(eng)
    install_append_only(eng)
    db_module.set_engine(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = db_module.get_session_factory()()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def seeded(db: Session) -> Session:
    """Chart of accounts, role mappings, starter users and the two go-live mandates."""
    seed.load_chart_of_accounts(db)
    seed.load_role_mappings(db)
    seed.seed_users(db, temporary=TEST_PASSWORD)
    seed.seed_clients(db)
    db.flush()
    return db


@pytest.fixture
def settings_obj() -> object:
    return get_settings()


def add_client(
    db: Session,
    client_id: str,
    *,
    base_currency: str = "USD",
    capital_code: str = "2130",
    profit_code: str = "2230",
    custody: tuple[str, str, str, str, str] = (
        "CUST",
        "USD",
        "1150",
        "1220",
        "Absa Bank Kenya PLC",
    ),
    fee_pct: str = "0.10",
    final_wht: str = "0",
) -> Client:
    """Create a minimal fully-onboarded client for a scenario test."""
    from app.models import AssetClass, RoleMapping

    client = Client(
        id=client_id,
        legal_name=f"{client_id} Test Mandate",
        base_currency=base_currency,
        kyc_status=KycStatus.APPROVED,
        kyc_reviewed_on=date(2025, 12, 31),
        agreement_ref=f"IMA/{client_id}/2025/1",
        agreement_date=date(2025, 12, 31),
        final_wht_rate=Decimal(final_wht),
        created_by="test",
    )
    db.add(client)
    acc_id, currency, cash, wakala, custodian = custody
    db.add(
        CustodyAccount(
            id=f"{client_id}-{acc_id}",
            client_id=client_id,
            custodian=custodian,
            custodian_address="Nairobi, Kenya",
            account_number=f"{client_id}-{acc_id}",
            currency=currency,
            cash_ledger_code=cash,
            wakala_ledger_code=wakala,
            custody_agreement_ref=f"CUSTODY/{client_id}/2025/1",
            is_default=True,
            created_by="test",
        )
    )
    db.add(RoleMapping(client_id=client_id, role="CLIENT_CAPITAL", account_code=capital_code))
    db.add(RoleMapping(client_id=client_id, role="CLIENT_PROFIT", account_code=profit_code))
    db.add(RoleMapping(client_id=client_id, role="WAKALA", account_code=wakala))
    for asset_class in AssetClass:
        db.add(
            MandateFee(
                client_id=client_id,
                asset_class=asset_class,
                fee_pct_of_income=Decimal(fee_pct),
                effective_from=date(2020, 1, 1),
                created_by="test",
            )
        )
    db.flush()
    return client


def add_custody_account(
    db: Session,
    client_id: str,
    acc_id: str,
    *,
    currency: str,
    cash_code: str,
    wakala_code: str,
    custodian: str = "Absa Bank Kenya PLC",
) -> CustodyAccount:
    account = CustodyAccount(
        id=acc_id,
        client_id=client_id,
        custodian=custodian,
        custodian_address="Nairobi, Kenya",
        account_number=acc_id,
        currency=currency,
        cash_ledger_code=cash_code,
        wakala_ledger_code=wakala_code,
        custody_agreement_ref=f"CUSTODY/{client_id}/2025/1",
        created_by="test",
    )
    db.add(account)
    db.flush()
    return account


def add_fx_rate(
    db: Session, currency: str, base: str, on: date, value: str, source: str = "CBK indicative mean"
) -> None:
    db.add(
        FxRate(
            currency=currency,
            base_currency=base,
            rate_date=on,
            rate=Decimal(value),
            source=source,
            entered_by="test",
            created_by="test",
        )
    )
    db.flush()


@contextmanager
def fresh_session() -> Iterator[Session]:
    """A brand new seeded database.

    Hypothesis reuses a function-scoped fixture across examples, so a property test
    builds its own database per example instead.
    """
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    install_append_only(engine)
    db_module.set_engine(engine)
    session = db_module.get_session_factory()()
    try:
        seed.load_chart_of_accounts(session)
        seed.load_role_mappings(session)
        seed.seed_users(session, temporary=TEST_PASSWORD)
        seed.seed_clients(session)
        session.flush()
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def run_instruction(
    db: Session,
    *,
    client_id: str,
    custody_account_id: str,
    instruction_type: object,
    amount: str,
    value_date: date,
    params: dict[str, object] | None = None,
    beneficiary: str = "<BENEFICIARY>",
    beneficiary_account: str = "<ACCOUNT>",
    client_instruction_ref: str | None = None,
    narrative: str = "",
    settled_on: date | None = None,
    confirmation_ref: str = "CUSTODIAN-CONF-1",
    maker: str = "ops.maker",
    signatories: tuple[str, str] = ("sig.one", "sig.two"),
    settler: str = "fin.head",
) -> object:
    """Drive one instruction end to end: create, two approvals, send, settle."""
    from app.models import InstructionType, User
    from app.services import instructions as ins

    instruction = ins.create(
        db,
        client_id=client_id,
        custody_account_id=custody_account_id,
        instruction_type=InstructionType(instruction_type),
        amount=Decimal(amount),
        value_date=value_date,
        maker_id=maker,
        beneficiary=beneficiary,
        beneficiary_account=beneficiary_account,
        narrative=narrative,
        client_instruction_ref=client_instruction_ref,
        params=params,
    )
    for signatory in signatories:
        user = db.get(User, signatory)
        assert user is not None
        ins.approve(db, instruction.id, approver=user)
    ins.mark_sent(
        db,
        instruction.id,
        user_id=maker,
        signed_copy_sha256="0" * 64,
    )
    ins.settle(
        db,
        instruction.id,
        user_id=settler,
        confirmation_ref=confirmation_ref,
        settled_on=settled_on or value_date,
        amount=Decimal(amount),
    )
    db.refresh(instruction)
    return instruction


def balance_of(
    db: Session, client_id: str, account_code: str, *, as_of: date | None = None, base: bool = False
) -> Decimal:
    from app.ledger import balances

    return balances.balance(
        db, client_id=client_id, account_code=account_code, as_of=as_of, base=base
    )


def line_amounts(entry: object) -> dict[str, str]:
    """{account_code: signed amount} for a posted entry, for readable assertions."""
    out: dict[str, str] = {}
    for line in entry.lines:  # type: ignore[attr-defined]
        key = line.account_code
        out[key] = f"{Decimal(out.get(key, '0')) + line.amount:.2f}"
    return out


__all__ = [
    "TEST_PASSWORD",
    "add_client",
    "add_custody_account",
    "add_fx_rate",
    "fresh_session",
    "line_amounts",
    "posting",
]

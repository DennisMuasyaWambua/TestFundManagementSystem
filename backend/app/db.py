"""Engine, session and the SQL types that keep money exact.

PostgreSQL 16 is the production database: money is ``NUMERIC(24,2)`` and rates are
``NUMERIC(24,8)``.  SQLite is supported for local development and the test suite,
where the same values are stored as scaled integers (cents, and rate * 1e8) so that
``SUM()`` stays exact -- SQLite would otherwise coerce NUMERIC to a float.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Engine, Numeric, String, create_engine, event, text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app import enums
from app.config import get_settings
from app.money import MONEY_SCALE, RATE_SCALE, money, rate

MONEY_FACTOR = Decimal(10) ** MONEY_SCALE
RATE_FACTOR = Decimal(10) ** RATE_SCALE


class _ScaledDecimal(TypeDecorator[Decimal]):
    """A fixed-scale decimal: NUMERIC on PostgreSQL, scaled BIGINT on SQLite."""

    impl = Numeric
    cache_ok = True
    scale = 2
    factor = MONEY_FACTOR

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(BigInteger())
        return dialect.type_descriptor(Numeric(precision=24, scale=self.scale, asdecimal=True))

    def _coerce(self, value: Any) -> Decimal:
        raise NotImplementedError

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        dec = self._coerce(value)
        if dialect.name == "sqlite":
            return int((dec * self.factor).to_integral_value())
        return dec

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        if dialect.name == "sqlite":
            return self._coerce(Decimal(int(value)) / self.factor)
        return self._coerce(value)


class MoneyT(_ScaledDecimal):
    """NUMERIC(24,2) -- an amount of money."""

    cache_ok = True
    scale = MONEY_SCALE
    factor = MONEY_FACTOR

    def _coerce(self, value: Any) -> Decimal:
        return money(value)


class RateT(_ScaledDecimal):
    """NUMERIC(24,8) -- an FX rate, profit rate or percentage."""

    cache_ok = True
    scale = RATE_SCALE
    factor = RATE_FACTOR

    def _coerce(self, value: Any) -> Decimal:
        return rate(value)


class EnumStr(TypeDecorator[Any]):
    """A string column that comes back as its enum member, not a bare string.

    Without this, ``account.status is RecordStatus.ACTIVE`` would quietly be false for
    a row loaded from the database, and every identity check in the business rules
    would be a silent no-op.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[StrEnum], length: int = 32) -> None:
        self.enum_cls = enum_cls
        super().__init__(length=length)

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        return None if value is None else self.enum_cls(value)


class Base(DeclarativeBase):
    """Declarative base.

    The annotation map means a model writes ``Mapped[RecordStatus]`` and gets the
    right column type and the right Python value back, with no per-column repetition.
    """

    type_annotation_map = {
        Decimal: MoneyT(),
        enums.AccountType: EnumStr(enums.AccountType, 16),
        enums.NormalBalance: EnumStr(enums.NormalBalance, 8),
        enums.ReportSection: EnumStr(enums.ReportSection, 4),
        enums.RecordStatus: EnumStr(enums.RecordStatus, 10),
        enums.UserRole: EnumStr(enums.UserRole, 16),
        enums.KycStatus: EnumStr(enums.KycStatus, 16),
        enums.RiskRating: EnumStr(enums.RiskRating, 8),
        enums.AssetClass: EnumStr(enums.AssetClass, 24),
        enums.HoldingStatus: EnumStr(enums.HoldingStatus, 16),
        enums.InstructionType: EnumStr(enums.InstructionType, 32),
        enums.InstructionStatus: EnumStr(enums.InstructionStatus, 24),
        enums.ApprovalStatus: EnumStr(enums.ApprovalStatus, 16),
        enums.BatchStatus: EnumStr(enums.BatchStatus, 16),
        enums.ProfitTreatment: EnumStr(enums.ProfitTreatment, 32),
        enums.FileKind: EnumStr(enums.FileKind, 32),
        enums.LedgerEvent: EnumStr(enums.LedgerEvent, 32),
    }


# --- Engine / session --------------------------------------------------------

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def make_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    target = url or settings.database_url
    kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if target.startswith("sqlite"):
        kwargs.pop("pool_pre_ping")
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(target, **kwargs)
    if target.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        _engine = make_engine()
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def set_engine(engine: Engine) -> None:
    """Point the application at a specific engine (used by tests and jobs)."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """One unit of work: everything commits together or nothing does."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_session() -> Iterator[Session]:
    """FastAPI dependency: one request, one transaction."""
    with session_scope() as session:
        yield session


# --- Append-only enforcement -------------------------------------------------

APPEND_ONLY_TABLES = ("journal_entries", "journal_lines", "audit_log")

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION fms_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table %% is append-only: correct mistakes with a reversal entry',
        TG_TABLE_NAME USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
"""


def append_only_ddl(dialect: str) -> list[str]:
    """DDL that makes the ledger and audit tables reject UPDATE and DELETE.

    This is enforced by the database, not only by application code, exactly as
    principle 3 of the build specification requires.
    """
    statements: list[str] = []
    if dialect == "postgresql":
        statements.append(_PG_FUNCTION)
        for table in APPEND_ONLY_TABLES:
            statements.append(
                f"CREATE TRIGGER {table}_append_only "
                f"BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION fms_append_only()"
            )
    elif dialect == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for verb in ("UPDATE", "DELETE"):
                statements.append(
                    f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only: "
                    f"correct mistakes with a reversal entry'); END"
                )
    else:  # pragma: no cover
        raise RuntimeError(f"no append-only DDL for dialect {dialect!r}")
    return statements


def drop_append_only_ddl(dialect: str) -> list[str]:
    if dialect == "postgresql":
        return [f"DROP TRIGGER IF EXISTS {t}_append_only ON {t}" for t in APPEND_ONLY_TABLES] + [
            "DROP FUNCTION IF EXISTS fms_append_only()"
        ]
    return [
        f"DROP TRIGGER IF EXISTS {t}_no_{verb}"
        for t in APPEND_ONLY_TABLES
        for verb in ("update", "delete")
    ]


def install_append_only(engine: Engine) -> None:
    with engine.begin() as conn:
        for stmt in append_only_ddl(engine.dialect.name):
            conn.execute(text(stmt))

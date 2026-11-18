"""The Alembic migration must build exactly the schema the models expect.

Three things are checked here, because each has its own way of going wrong:

* ``upgrade head`` runs, and ``downgrade base`` undoes it (a migration you cannot
  roll back is not a migration you can deploy);
* the migrated schema matches ``Base.metadata`` table for table and column for
  column, so a model change without a migration fails CI rather than production;
* the append-only triggers really are installed by the migration, not only by the
  test helper, so the ledger is protected in a migrated database too.

CI runs the same assertions against PostgreSQL 16 by setting ``FMS_DATABASE_URL``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db import APPEND_ONLY_TABLES, Base
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Tables the models do not own: Alembic's own bookkeeping.
NON_MODEL_TABLES = {"alembic_version"}


def _config(url: str) -> Config:
    """Alembic driven in-process, against an explicit URL.

    ``env.py`` only falls back to the application settings when the caller has not
    pinned a URL, so this cannot touch the real database.
    """
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="module")
def migrated_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A database built by the migration, not by ``create_all``.

    CI points ``FMS_MIGRATION_TEST_URL`` at PostgreSQL 16 to run the same assertions
    against the production database engine.
    """
    configured = os.environ.get("FMS_MIGRATION_TEST_URL")
    if configured:
        command.downgrade(_config(configured), "base")
        command.upgrade(_config(configured), "head")
        return configured
    path = tmp_path_factory.mktemp("migrated") / "fms.sqlite"
    url = f"sqlite+pysqlite:///{path.as_posix()}"
    command.upgrade(_config(url), "head")
    return url


def test_migration_builds_the_schema_the_models_expect(migrated_url: str) -> None:
    engine = create_engine(migrated_url)
    try:
        inspector = inspect(engine)
        migrated = set(inspector.get_table_names()) - NON_MODEL_TABLES
        expected = set(Base.metadata.tables)
        assert migrated == expected, (
            f"only in the migration: {sorted(migrated - expected)}; "
            f"only in the models: {sorted(expected - migrated)}"
        )

        for name, table in sorted(Base.metadata.tables.items()):
            migrated_columns = {col["name"]: col for col in inspector.get_columns(name)}
            assert set(migrated_columns) == set(table.columns.keys()), name
            for column in table.columns:
                assert migrated_columns[column.name]["nullable"] == column.nullable, (
                    f"{name}.{column.name} nullability differs"
                )
    finally:
        engine.dispose()


# One minimal row per append-only table, so the FOR EACH ROW triggers have a row to
# fire on.  An empty table would pass any UPDATE silently and prove nothing.
SEED_ROWS: tuple[tuple[str, str], ...] = (
    (
        "journal_entries",
        "INSERT INTO journal_entries "
        "(id, entry_date, event, client_id, currency, narrative, created_by) "
        "VALUES (1, '2026-01-31', 'OPENING_BALANCE', 'X', 'USD', 'test', 'system')",
    ),
    (
        "journal_lines",
        "INSERT INTO journal_lines "
        "(entry_id, account_code, client_id, amount, currency, fx_rate, base_amount, "
        "description) VALUES (1, '1140', 'X', 1, 'USD', 1, 1, 'test')",
    ),
    (
        "audit_log",
        "INSERT INTO audit_log (at, user_id, action, entity, detail) "
        "VALUES ('2026-01-31 00:00:00', 'system', 'TEST', 'test', '{}')",
    ),
)

# A column that exists on every one of these tables, so one UPDATE shape covers all.
TAMPER_COLUMN = {
    "journal_entries": "created_by",
    "journal_lines": "description",
    "audit_log": "action",
}


def test_migrated_database_rejects_update_and_delete(migrated_url: str) -> None:
    """The migration itself installs the append-only protection, not just the fixtures."""
    engine = create_engine(migrated_url)
    try:
        with engine.begin() as conn:
            for _, statement in SEED_ROWS:
                conn.execute(text(statement))

        assert {name for name, _ in SEED_ROWS} == set(APPEND_ONLY_TABLES)

        for table, _ in SEED_ROWS:
            for statement in (
                f"UPDATE {table} SET {TAMPER_COLUMN[table]} = 'tamper'",
                f"DELETE FROM {table}",
            ):
                with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
                    conn.execute(text(statement))

            # The row survived: the database refused the change, it did not swallow it.
            with engine.connect() as conn:
                assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 1
    finally:
        engine.dispose()


def test_downgrade_removes_everything(tmp_path: Path) -> None:
    if os.environ.get("FMS_MIGRATION_TEST_URL"):
        pytest.skip("destructive: only run against the throwaway SQLite database")
    url = f"sqlite+pysqlite:///{(tmp_path / 'down.sqlite').as_posix()}"
    command.upgrade(_config(url), "head")
    command.downgrade(_config(url), "base")
    engine = create_engine(url)
    try:
        remaining = set(inspect(engine).get_table_names()) - NON_MODEL_TABLES
        assert remaining == set()
    finally:
        engine.dispose()

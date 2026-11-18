"""initial schema

Creates every table in section 5 of the build specification and installs the
append-only triggers that make the journal and the audit log correctable only by a
reversal entry (principle 3).

Money is ``NUMERIC(24,2)`` and rates are ``NUMERIC(24,8)``.  This file holds plain
SQL types on purpose: a migration is a historical record of the database and must
keep working after the application's Python types are renamed or refactored.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = ("journal_entries", "journal_lines", "audit_log")

PG_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION fms_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only: correct mistakes with a reversal entry',
        TG_TABLE_NAME USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
"""


def _install_append_only(dialect: str) -> None:
    """Reject UPDATE and DELETE on the ledger and audit tables in the database itself."""
    if dialect == "postgresql":
        op.execute(PG_APPEND_ONLY_FUNCTION)
        for table in APPEND_ONLY_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_append_only "
                f"BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION fms_append_only()"
            )
    elif dialect == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for verb in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only: "
                    f"correct mistakes with a reversal entry'); END"
                )
    else:
        raise RuntimeError(f"no append-only DDL for dialect {dialect!r}")


def _drop_append_only(dialect: str) -> None:
    if dialect == "postgresql":
        for table in APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute("DROP FUNCTION IF EXISTS fms_append_only()")
    else:
        for table in APPEND_ONLY_TABLES:
            for verb in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{verb}")


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("parent_code", sa.String(length=10), nullable=True),
        sa.Column("is_postable", sa.Boolean(), nullable=False),
        sa.Column("normal_balance", sa.String(length=8), nullable=False),
        sa.Column("report", sa.String(length=4), nullable=False),
        sa.Column("needs_holding", sa.Boolean(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("sub_ledger", sa.String(length=32), nullable=True),
        sa.Column("is_proposed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=32), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_at", "audit_log", ["at"], unique=False)
    op.create_index("ix_audit_entity", "audit_log", ["entity", "entity_id"], unique=False)
    op.create_index(op.f("ix_audit_log_client_id"), "audit_log", ["client_id"], unique=False)
    op.create_table(
        "clients",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("kyc_status", sa.String(length=16), nullable=False),
        sa.Column("kyc_reviewed_on", sa.Date(), nullable=True),
        sa.Column("aml_risk_rating", sa.String(length=8), nullable=True),
        sa.Column("agreement_ref", sa.String(length=80), nullable=True),
        sa.Column("agreement_date", sa.Date(), nullable=True),
        sa.Column("final_wht_rate", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "custodian_balances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("custody_account_id", sa.String(length=48), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("statement_ref", sa.String(length=120), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("custody_account_id", "as_of", name="uq_custodian_balance"),
    )
    op.create_index(
        op.f("ix_custodian_balances_custody_account_id"),
        "custodian_balances",
        ["custody_account_id"],
        unique=False,
    )
    op.create_table(
        "custodian_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("holding_id", sa.String(length=48), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("statement_ref", sa.String(length=120), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("holding_id", "as_of", name="uq_custodian_position"),
    )
    op.create_index(
        op.f("ix_custodian_positions_holding_id"),
        "custodian_positions",
        ["holding_id"],
        unique=False,
    )
    op.create_table(
        "custody_accounts",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("custodian", sa.String(length=160), nullable=False),
        sa.Column("custodian_address", sa.String(length=400), nullable=False),
        sa.Column("custodian_contact", sa.String(length=160), nullable=False),
        sa.Column("account_number", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cash_ledger_code", sa.String(length=10), nullable=False),
        sa.Column("wakala_ledger_code", sa.String(length=10), nullable=False),
        sa.Column("custody_agreement_ref", sa.String(length=80), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_number", "currency", name="uq_custody_account"),
    )
    op.create_index(
        op.f("ix_custody_accounts_client_id"), "custody_accounts", ["client_id"], unique=False
    )
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column("uploaded_by", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_files_sha256"), "files", ["sha256"], unique=False)
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("entered_by", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("currency", "base_currency", "rate_date", name="uq_fx_rate"),
    )
    op.create_index(
        "ix_fx_rates_lookup", "fx_rates", ["currency", "base_currency", "rate_date"], unique=False
    )
    op.create_table(
        "holdings",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("asset_class", sa.String(length=24), nullable=False),
        sa.Column("custody_account_id", sa.String(length=48), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=False),
        sa.Column("related_party", sa.Boolean(), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("face_amount", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("nominal", sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column("profit_rate", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("day_basis", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("monthly_rent", sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column("accrual_start", sa.Date(), nullable=True),
        sa.Column("opening_accrued", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("opening_batch_id", sa.Integer(), nullable=True),
        sa.Column("shariah_cert_ref", sa.String(length=120), nullable=True),
        sa.Column("external_ref", sa.String(length=120), nullable=True),
        sa.Column("instruction_id", sa.Integer(), nullable=True),
        sa.Column("is_placeholder", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_holdings_asset_class"), "holdings", ["asset_class"], unique=False)
    op.create_index(op.f("ix_holdings_client_id"), "holdings", ["client_id"], unique=False)
    op.create_table(
        "instructions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reference", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("custody_account_id", sa.String(length=48), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("holding_id", sa.String(length=48), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("beneficiary", sa.String(length=300), nullable=False),
        sa.Column("beneficiary_account", sa.String(length=200), nullable=False),
        sa.Column("narrative", sa.String(length=600), nullable=False),
        sa.Column("client_instruction_ref", sa.String(length=120), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("maker_id", sa.String(length=32), nullable=False),
        sa.Column("letter_pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("signed_copy_sha256", sa.String(length=64), nullable=True),
        sa.Column("signed_copy_blob_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("sent_by", sa.String(length=32), nullable=True),
        sa.Column("custodian_confirmation_ref", sa.String(length=120), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("settled_on", sa.Date(), nullable=True),
        sa.Column("settled_by", sa.String(length=32), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=400), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index(op.f("ix_instructions_client_id"), "instructions", ["client_id"], unique=False)
    op.create_index(op.f("ix_instructions_status"), "instructions", ["status"], unique=False)
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("narrative", sa.String(length=400), nullable=False),
        sa.Column("instruction_id", sa.Integer(), nullable=True),
        sa.Column("reverses_id", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_journal_entries_batch_id"), "journal_entries", ["batch_id"], unique=False
    )
    op.create_index(
        "ix_journal_entries_client_date",
        "journal_entries",
        ["client_id", "entry_date"],
        unique=False,
    )
    op.create_index("ix_journal_entries_event", "journal_entries", ["event"], unique=False)
    op.create_index(
        op.f("ix_journal_entries_instruction_id"),
        "journal_entries",
        ["instruction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_journal_entries_reference"), "journal_entries", ["reference"], unique=False
    )
    op.create_index(
        op.f("ix_journal_entries_reverses_id"), "journal_entries", ["reverses_id"], unique=False
    )
    op.create_table(
        "mandate_fees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("asset_class", sa.String(length=24), nullable=False),
        sa.Column("fee_pct_of_income", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "asset_class", "effective_from", name="uq_mandate_fee"),
    )
    op.create_index(op.f("ix_mandate_fees_client_id"), "mandate_fees", ["client_id"], unique=False)
    op.create_table(
        "manual_journals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("narrative", sa.String(length=400), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prepared_by", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=32), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=400), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_manual_journals_client_id"), "manual_journals", ["client_id"], unique=False
    )
    op.create_table(
        "opening_balance_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("cutover_date", sa.Date(), nullable=False),
        sa.Column("profit_treatment", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pro_rata_accrual_split", sa.Boolean(), nullable=False),
        sa.Column("source_files", sa.JSON(), nullable=False),
        sa.Column("validation_report", sa.JSON(), nullable=False),
        sa.Column("warnings_acknowledged_by", sa.String(length=32), nullable=True),
        sa.Column("warnings_acknowledged_note", sa.String(length=600), nullable=True),
        sa.Column("prepared_by", sa.String(length=32), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.String(length=32), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=600), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("reverses_batch_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opening_balance_batches_client_id"),
        "opening_balance_batches",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opening_balance_batches_status"),
        "opening_balance_batches",
        ["status"],
        unique=False,
    )
    op.create_table(
        "period_locks",
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("locked_through", sa.Date(), nullable=False),
        sa.Column("locked_by", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("performed_by", sa.String(length=32), nullable=False),
        sa.Column("performed_at", sa.DateTime(), nullable=False),
        sa.Column("breaks", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_reconciliation_runs_client_id"), "reconciliation_runs", ["client_id"], unique=False
    )
    op.create_table(
        "reference_sequences",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name", "year"),
    )
    op.create_table(
        "role_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=48), nullable=False),
        sa.Column("account_code", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "role", name="uq_role_mapping"),
    )
    op.create_table(
        "user_client_access",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "client_id", name="uq_user_client"),
    )
    op.create_index(
        op.f("ix_user_client_access_user_id"), "user_client_access", ["user_id"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("can_login", sa.Boolean(), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("totp_secret", sa.String(length=256), nullable=True),
        sa.Column("totp_enrolled", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "valuations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("holding_id", sa.String(length=48), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("value", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("valuer_name", sa.String(length=200), nullable=True),
        sa.Column("report_ref", sa.String(length=120), nullable=True),
        sa.Column("report_file_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prepared_by", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=32), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=400), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_valuations_client_id"), "valuations", ["client_id"], unique=False)
    op.create_index(op.f("ix_valuations_holding_id"), "valuations", ["holding_id"], unique=False)
    op.create_table(
        "instruction_approvals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instruction_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["instruction_id"],
            ["instructions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instruction_id", "user_id", name="uq_instruction_approver"),
    )
    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(length=10), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("holding_id", sa.String(length=48), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fx_rate", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("base_amount", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["journal_entries.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journal_lines_client_account",
        "journal_lines",
        ["client_id", "account_code"],
        unique=False,
    )
    op.create_index("ix_journal_lines_entry", "journal_lines", ["entry_id"], unique=False)
    op.create_index("ix_journal_lines_holding", "journal_lines", ["holding_id"], unique=False)
    op.create_table(
        "opening_balance_custodian_rows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("statement_ref", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["opening_balance_batches.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opening_balance_custodian_rows_batch_id"),
        "opening_balance_custodian_rows",
        ["batch_id"],
        unique=False,
    )
    op.create_table(
        "opening_balance_holdings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("holding_id", sa.String(length=48), nullable=False),
        sa.Column("asset_class", sa.String(length=24), nullable=False),
        sa.Column("custody_account", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=False),
        sa.Column("face_amount", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("nominal", sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column("profit_rate", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("day_basis", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("monthly_rent", sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column("shariah_cert_ref", sa.String(length=120), nullable=True),
        sa.Column("external_ref", sa.String(length=120), nullable=True),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("is_placeholder", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["opening_balance_batches.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opening_balance_holdings_batch_id"),
        "opening_balance_holdings",
        ["batch_id"],
        unique=False,
    )
    op.create_table(
        "opening_balance_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(length=10), nullable=False),
        sa.Column("holding_id", sa.String(length=48), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("debit", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("credit", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("derived", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["opening_balance_batches.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opening_balance_lines_batch_id"),
        "opening_balance_lines",
        ["batch_id"],
        unique=False,
    )
    _install_append_only(op.get_bind().dialect.name)


def downgrade() -> None:
    _drop_append_only(op.get_bind().dialect.name)
    op.drop_index(op.f("ix_opening_balance_lines_batch_id"), table_name="opening_balance_lines")
    op.drop_table("opening_balance_lines")
    op.drop_index(
        op.f("ix_opening_balance_holdings_batch_id"), table_name="opening_balance_holdings"
    )
    op.drop_table("opening_balance_holdings")
    op.drop_index(
        op.f("ix_opening_balance_custodian_rows_batch_id"),
        table_name="opening_balance_custodian_rows",
    )
    op.drop_table("opening_balance_custodian_rows")
    op.drop_index("ix_journal_lines_holding", table_name="journal_lines")
    op.drop_index("ix_journal_lines_entry", table_name="journal_lines")
    op.drop_index("ix_journal_lines_client_account", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_table("instruction_approvals")
    op.drop_index(op.f("ix_valuations_holding_id"), table_name="valuations")
    op.drop_index(op.f("ix_valuations_client_id"), table_name="valuations")
    op.drop_table("valuations")
    op.drop_table("users")
    op.drop_index(op.f("ix_user_client_access_user_id"), table_name="user_client_access")
    op.drop_table("user_client_access")
    op.drop_table("role_mappings")
    op.drop_table("reference_sequences")
    op.drop_index(op.f("ix_reconciliation_runs_client_id"), table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
    op.drop_table("period_locks")
    op.drop_index(op.f("ix_opening_balance_batches_status"), table_name="opening_balance_batches")
    op.drop_index(
        op.f("ix_opening_balance_batches_client_id"), table_name="opening_balance_batches"
    )
    op.drop_table("opening_balance_batches")
    op.drop_index(op.f("ix_manual_journals_client_id"), table_name="manual_journals")
    op.drop_table("manual_journals")
    op.drop_index(op.f("ix_mandate_fees_client_id"), table_name="mandate_fees")
    op.drop_table("mandate_fees")
    op.drop_index(op.f("ix_journal_entries_reverses_id"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_reference"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_instruction_id"), table_name="journal_entries")
    op.drop_index("ix_journal_entries_event", table_name="journal_entries")
    op.drop_index("ix_journal_entries_client_date", table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_batch_id"), table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index(op.f("ix_instructions_status"), table_name="instructions")
    op.drop_index(op.f("ix_instructions_client_id"), table_name="instructions")
    op.drop_table("instructions")
    op.drop_index(op.f("ix_holdings_client_id"), table_name="holdings")
    op.drop_index(op.f("ix_holdings_asset_class"), table_name="holdings")
    op.drop_table("holdings")
    op.drop_index("ix_fx_rates_lookup", table_name="fx_rates")
    op.drop_table("fx_rates")
    op.drop_index(op.f("ix_files_sha256"), table_name="files")
    op.drop_table("files")
    op.drop_index(op.f("ix_custody_accounts_client_id"), table_name="custody_accounts")
    op.drop_table("custody_accounts")
    op.drop_index(op.f("ix_custodian_positions_holding_id"), table_name="custodian_positions")
    op.drop_table("custodian_positions")
    op.drop_index(op.f("ix_custodian_balances_custody_account_id"), table_name="custodian_balances")
    op.drop_table("custodian_balances")
    op.drop_table("clients")
    op.drop_index(op.f("ix_audit_log_client_id"), table_name="audit_log")
    op.drop_index("ix_audit_entity", table_name="audit_log")
    op.drop_index("ix_audit_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("accounts")

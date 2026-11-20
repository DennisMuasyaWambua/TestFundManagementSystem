"""Opening balance migration.

Each client's position as at close of business on the cutover date is loaded once, as
a batch.  Rows are staged, validated, previewed and only then posted; nothing touches
the ledger until the batch reaches POSTED.

A posted batch can only be undone by a reversal batch.  This test system does not set
a period lock on posting, and does not require the approver to be someone other than
the preparer -- see _assert_approver and the end of post().
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import BusinessRule, Conflict, MakerCheckerBreach, NotFound, ValidationFailed
from app.ledger import fx as fx_rates
from app.ledger.posting import LineDraft, post
from app.ledger.roles import Role, client_owned_accounts, resolve
from app.models import (
    Account,
    AccountType,
    AssetClass,
    BatchStatus,
    Client,
    CustodyAccount,
    Holding,
    HoldingStatus,
    JournalEntry,
    LedgerEvent,
    OpeningBalanceBatch,
    OpeningBalanceHolding,
    OpeningBalanceLine,
    OpeningCustodianRow,
    ProfitTreatment,
    RecordStatus,
    User,
    UserRole,
    utcnow,
)
from app.money import ZERO, money, round_money, split_pro_rata
from app.services import audit
from app.services import reconciliation as recon_svc

TEMPLATES = {
    "holdings": (
        "holding_id,asset_class,custody_account,currency,counterparty,face_amount,nominal,"
        "profit_rate,day_basis,start_date,maturity_date,monthly_rent,shariah_cert_ref,"
        "external_ref,description,is_placeholder\n"
        "FD-R-03,WAKALA,CR0012A,USD,Absa Bank Kenya PLC,1000000.00,,0.0425,365,01-01-2026,"
        "14-08-2026,,SSB/<REF>,<BANK REF>,Wakala fixed deposit,0\n"
    ),
    "lines": (
        "account_code,holding_id,currency,debit,credit,description\n"
        "1220,FD-R-03,USD,1000000.00,,Wakala deposit\n"
        "1310,FD-R-03,USD,0.00,,Accrued profit to cutover\n"
        "1140,,USD,10710.53,,Bank balance\n"
        "2310,,USD,,10453.08,Payables\n"
        "2110,,USD,,5000000.00,Initial investment\n"
        "2210,,USD,,411680.53,Profit brought forward\n"
        "2210,,USD,,196927.56,Current year profit to date\n"
        "2210,,USD,117940.86,,Profit paid to date\n"
    ),
    "custodian_balances": (
        "custody_account,as_of,balance,statement_ref\nCR0012A,31-01-2026,10710.53,<STATEMENT REF>\n"
    ),
    "custodian_positions": (
        "holding_id,as_of,amount,statement_ref\nFD-R-03,31-01-2026,1000000.00,<STATEMENT REF>\n"
    ),
}

ACCRUED_ROLE = Role.ACCRUED_INCOME
SUSPENSE_ROLE = Role.SUSPENSE


@dataclass
class Finding:
    level: str
    code: str
    message: str
    row: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "code": self.code, "message": self.message, "row": self.row}


@dataclass
class ValidationReport:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    totals: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "errors": [f.as_dict() for f in self.errors],
            "warnings": [f.as_dict() for f in self.warnings],
            "totals": self.totals,
            "ok": self.ok,
        }


# --- Batch lifecycle ---------------------------------------------------------


def create_batch(
    db: Session,
    *,
    client_id: str,
    cutover_date: date,
    prepared_by: str,
    profit_treatment: ProfitTreatment = ProfitTreatment.CLIENT_PROFIT_ONLY,
    pro_rata_accrual_split: bool = False,
) -> OpeningBalanceBatch:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)

    # A real deployment refuses a second posted batch for the same client here --
    # on this test system that restriction is deliberately lifted, so any number of
    # batches (including several posted ones) can be created against one client
    # while exploring the flow.

    batch = OpeningBalanceBatch(
        client_id=client_id,
        cutover_date=cutover_date,
        profit_treatment=profit_treatment,
        pro_rata_accrual_split=pro_rata_accrual_split,
        status=BatchStatus.DRAFT,
        prepared_by=prepared_by,
        created_by=prepared_by,
    )
    db.add(batch)
    db.flush()
    audit.record(
        db,
        user_id=prepared_by,
        action="OPENING_BATCH_CREATED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=client_id,
        detail={
            "cutover_date": cutover_date.isoformat(),
            "profit_treatment": str(profit_treatment),
            "pro_rata_accrual_split": pro_rata_accrual_split,
        },
    )
    return batch


def _editable(batch: OpeningBalanceBatch) -> None:
    # A real deployment would stop here once a batch is SUBMITTED (awaiting a second
    # person's decision) or REJECTED -- on this test system, replacing a file or
    # re-validating is allowed right up to POSTED, which is the one point past which
    # there's a real ledger entry to protect. Re-validating (see _finish() below)
    # resets the status to DRAFT or VALIDATED either way, which is what actually
    # takes a SUBMITTED batch back out of the approval queue.
    if batch.status is BatchStatus.POSTED:
        raise Conflict(
            f"batch {batch.id} is posted and can no longer be changed",
            status=str(batch.status),
        )


def update_client(
    db: Session, batch: OpeningBalanceBatch, *, client_id: str, user_id: str
) -> OpeningBalanceBatch:
    """Correct which mandate a batch not yet posted belongs to.

    Every account and custody reference the uploaded CSVs resolve against is the
    client's own chart of accounts, so changing it makes whatever validation
    already ran meaningless -- the batch drops back to DRAFT (and any warning
    acknowledgement is cleared with it) so it has to be validated again. The
    uploaded rows are left as they are; if they do not belong to the new client,
    validation will say so (e.g. an unknown custody account) rather than this
    silently discarding them.
    """
    _editable(batch)
    if client_id == batch.client_id:
        return batch
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    previous = batch.client_id
    batch.client_id = client_id
    batch.status = BatchStatus.DRAFT
    batch.validation_report = {}
    batch.warnings_acknowledged_by = None
    batch.warnings_acknowledged_note = None
    db.flush()
    audit.record(
        db,
        user_id=user_id,
        action="OPENING_BATCH_CLIENT_CHANGED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=client_id,
        detail={"previous": previous, "new": client_id},
    )
    return batch


def update_cutover_date(
    db: Session, batch: OpeningBalanceBatch, *, cutover_date: date, user_id: str
) -> OpeningBalanceBatch:
    """Correct the "as at when" on a batch that has not been posted yet.

    Every custodian row and the preview's accrual maths is checked against this
    date, so changing it makes whatever validation already ran meaningless -- the
    batch drops back to DRAFT (and any warning acknowledgement is cleared with it)
    so it has to be validated again before it can be submitted.
    """
    _editable(batch)
    if cutover_date == batch.cutover_date:
        return batch
    previous = batch.cutover_date
    batch.cutover_date = cutover_date
    batch.status = BatchStatus.DRAFT
    batch.validation_report = {}
    batch.warnings_acknowledged_by = None
    batch.warnings_acknowledged_note = None
    db.flush()
    audit.record(
        db,
        user_id=user_id,
        action="OPENING_BATCH_CUTOVER_DATE_CHANGED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=batch.client_id,
        detail={"previous": previous.isoformat(), "new": cutover_date.isoformat()},
    )
    return batch


def _decimal(raw: str | None, *, field_name: str, row: int) -> Decimal | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return money(Decimal(text))
    except (InvalidOperation, ArithmeticError, ValueError) as exc:
        raise ValidationFailed(
            f"row {row}: {field_name} is not a valid amount ({text!r})", row=row, field=field_name
        ) from exc


def _rate(raw: str | None, *, field_name: str, row: int) -> Decimal | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ArithmeticError, ValueError) as exc:
        raise ValidationFailed(
            f"row {row}: {field_name} is not a valid rate ({text!r})", row=row, field=field_name
        ) from exc


def _date(raw: str | None, *, field_name: str, row: int) -> date | None:
    """Every date column in these CSVs is day-month-year, e.g. 31-01-2026 or 31/01/2026."""
    text = (raw or "").strip()
    if not text:
        return None
    for pattern in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValidationFailed(
        f"row {row}: {field_name} is not a day-month-year date ({text!r}); "
        "expected the form 31-01-2026 or 31/01/2026",
        row=row,
        field=field_name,
    )


def load_holdings(db: Session, batch: OpeningBalanceBatch, content: str) -> int:
    _editable(batch)
    for existing in list(batch.holdings):
        db.delete(existing)
    db.flush()
    count = 0
    for index, row in enumerate(csv.DictReader(io.StringIO(content)), start=2):
        holding_id = (row.get("holding_id") or "").strip()
        if not holding_id:
            continue
        face = _decimal(row.get("face_amount"), field_name="face_amount", row=index)
        if face is None:
            raise ValidationFailed(f"row {index}: face_amount is required", row=index)
        db.add(
            OpeningBalanceHolding(
                batch_id=batch.id,
                row_number=index,
                holding_id=holding_id,
                asset_class=AssetClass((row.get("asset_class") or "").strip()),
                custody_account=(row.get("custody_account") or "").strip(),
                currency=(row.get("currency") or "").strip().upper(),
                counterparty=(row.get("counterparty") or "").strip(),
                face_amount=face,
                nominal=_decimal(row.get("nominal"), field_name="nominal", row=index),
                profit_rate=_rate(row.get("profit_rate"), field_name="profit_rate", row=index),
                day_basis=int(row.get("day_basis") or get_settings().default_day_basis),
                start_date=_date(row.get("start_date"), field_name="start_date", row=index),
                maturity_date=_date(
                    row.get("maturity_date"), field_name="maturity_date", row=index
                ),
                monthly_rent=_decimal(
                    row.get("monthly_rent"), field_name="monthly_rent", row=index
                ),
                shariah_cert_ref=(row.get("shariah_cert_ref") or "").strip() or None,
                external_ref=(row.get("external_ref") or "").strip() or None,
                description=(row.get("description") or "").strip(),
                is_placeholder=(row.get("is_placeholder") or "").strip() in ("1", "true", "TRUE"),
                created_by=batch.prepared_by,
            )
        )
        count += 1
    batch.status = BatchStatus.DRAFT
    db.flush()
    return count


def load_lines(db: Session, batch: OpeningBalanceBatch, content: str) -> int:
    _editable(batch)
    for existing in list(batch.lines):
        db.delete(existing)
    db.flush()
    count = 0
    for index, row in enumerate(csv.DictReader(io.StringIO(content)), start=2):
        code = (row.get("account_code") or "").strip()
        if not code:
            continue
        debit = _decimal(row.get("debit"), field_name="debit", row=index) or ZERO
        credit = _decimal(row.get("credit"), field_name="credit", row=index) or ZERO
        if debit != 0 and credit != 0:
            raise ValidationFailed(
                f"row {index}: a line carries either a debit or a credit, not both", row=index
            )
        if debit == 0 and credit == 0:
            continue
        db.add(
            OpeningBalanceLine(
                batch_id=batch.id,
                row_number=index,
                account_code=code,
                holding_id=(row.get("holding_id") or "").strip() or None,
                currency=(row.get("currency") or "").strip().upper(),
                debit=debit,
                credit=credit,
                description=(row.get("description") or "").strip(),
                created_by=batch.prepared_by,
            )
        )
        count += 1
    batch.status = BatchStatus.DRAFT
    db.flush()
    return count


def load_custodian_rows(db: Session, batch: OpeningBalanceBatch, content: str, *, kind: str) -> int:
    _editable(batch)
    for existing in db.execute(
        select(OpeningCustodianRow).where(
            OpeningCustodianRow.batch_id == batch.id, OpeningCustodianRow.kind == kind
        )
    ).scalars():
        db.delete(existing)
    db.flush()
    key_field = "custody_account" if kind == "BALANCE" else "holding_id"
    amount_field = "balance" if kind == "BALANCE" else "amount"
    count = 0
    for index, row in enumerate(csv.DictReader(io.StringIO(content)), start=2):
        key = (row.get(key_field) or "").strip()
        if not key:
            continue
        as_of = _date(row.get("as_of"), field_name="as_of", row=index)
        amount = _decimal(row.get(amount_field), field_name=amount_field, row=index)
        if as_of is None or amount is None:
            raise ValidationFailed(
                f"row {index}: as_of and {amount_field} are both required", row=index
            )
        db.add(
            OpeningCustodianRow(
                batch_id=batch.id,
                kind=kind,
                key=key,
                as_of=as_of,
                amount=amount,
                statement_ref=(row.get("statement_ref") or "").strip(),
                created_by=batch.prepared_by,
            )
        )
        count += 1
    batch.status = BatchStatus.DRAFT
    db.flush()
    return count


# --- Validation --------------------------------------------------------------


def _custody_account(db: Session, batch: OpeningBalanceBatch, key: str) -> CustodyAccount | None:
    account = db.get(CustodyAccount, key)
    if account is not None and account.client_id == batch.client_id:
        return account
    return db.execute(
        select(CustodyAccount).where(
            CustodyAccount.client_id == batch.client_id, CustodyAccount.account_number == key
        )
    ).scalar_one_or_none()


def _investment_account(
    db: Session, batch: OpeningBalanceBatch, row: OpeningBalanceHolding
) -> str | None:
    custody = _custody_account(db, batch, row.custody_account)
    if custody is None:
        return None
    return resolve(
        db, batch.client_id, Role.INVESTMENT, custody_account=custody, asset_class=row.asset_class
    )


def _money_or_none(amount: Decimal | None) -> str | None:
    """Render an optional amount for a JSON payload: money travels as a string."""
    return None if amount is None else f"{amount:.2f}"


def expected_accrual(row: OpeningBalanceHolding, cutover: date) -> Decimal | None:
    """Recompute profit from the holding's start date to the cutover, for the check."""
    if row.profit_rate is None or row.start_date is None:
        return None
    last = cutover
    if row.maturity_date is not None:
        last = min(last, row.maturity_date - timedelta(days=1))
    days = (last - row.start_date).days + 1
    if days <= 0:
        return ZERO
    base = row.nominal if row.asset_class is AssetClass.SUKUK and row.nominal else row.face_amount
    return round_money(base * row.profit_rate * Decimal(days) / Decimal(row.day_basis))


def validate(db: Session, batch: OpeningBalanceBatch) -> ValidationReport:
    """Run every check in section 7.3.  Errors block; warnings need acknowledgement.

    Re-running this on a SUBMITTED or REJECTED batch (allowed on this test system,
    see _editable()) is what actually reopens it: _finish() below always sets the
    status from the validation outcome alone, so a re-validate takes it straight
    back to DRAFT or VALIDATED regardless of what it was before.
    """
    if batch.status is BatchStatus.POSTED:
        raise Conflict(f"batch {batch.id} is posted", status=str(batch.status))

    report = ValidationReport()
    cutover = batch.cutover_date
    accrued_code = resolve(db, batch.client_id, ACCRUED_ROLE)
    owners = client_owned_accounts(db)

    # A previous run of _apply_pro_rata_split() below deletes the uploaded lump-sum
    # line outright once it is split, so a second run would find nothing left to
    # split and silently drop the figure from the batch. Rebuilding that lump sum
    # from its derived children -- before they are cleared below -- is what makes
    # re-running validation (the "Re-validate" button, or a cutover date
    # correction) repeatable instead of destructive the second time.
    pro_rata_splits: dict[int, list[OpeningBalanceLine]] = {}
    for line in batch.lines:
        if line.derived and line.account_code == accrued_code and line.holding_id:
            pro_rata_splits.setdefault(line.row_number, []).append(line)
    for row_number, split_lines in pro_rata_splits.items():
        total = sum((split_line.signed for split_line in split_lines), ZERO)
        db.add(
            OpeningBalanceLine(
                batch_id=batch.id,
                row_number=row_number,
                account_code=accrued_code,
                currency=split_lines[0].currency,
                debit=total if total > 0 else ZERO,
                credit=-total if total < 0 else ZERO,
                description="accrued profit, pending the pro-rata split below",
                created_by=batch.prepared_by,
            )
        )

    # drop any previously derived rows so validation is repeatable
    for line in [line for line in batch.lines if line.derived]:
        db.delete(line)
    db.flush()
    db.refresh(batch)

    if not batch.holdings and not batch.lines:
        report.errors.append(Finding("error", "NO_ROWS", "no holdings or journal lines loaded"))
        return _finish(db, batch, report)

    holdings_by_id = {row.holding_id: row for row in batch.holdings}

    # --- holdings -----------------------------------------------------------
    for row in batch.holdings:
        custody = _custody_account(db, batch, row.custody_account)
        if custody is None:
            report.errors.append(
                Finding(
                    "error",
                    "UNKNOWN_CUSTODY_ACCOUNT",
                    f"{row.holding_id}: custody account {row.custody_account!r} is not one of "
                    f"{batch.client_id}'s accounts",
                    row.row_number,
                )
            )
        elif custody.currency != row.currency:
            report.errors.append(
                Finding(
                    "error",
                    "CURRENCY_MISMATCH",
                    f"{row.holding_id}: currency {row.currency} does not match custody account "
                    f"{custody.account_number} ({custody.currency})",
                    row.row_number,
                )
            )
        if row.face_amount <= 0:
            report.errors.append(
                Finding(
                    "error",
                    "BAD_FACE_AMOUNT",
                    f"{row.holding_id}: face amount must be more than zero",
                    row.row_number,
                )
            )
        if db.get(Holding, row.holding_id) is not None:
            report.errors.append(
                Finding(
                    "error",
                    "HOLDING_EXISTS",
                    f"{row.holding_id} already exists in the system",
                    row.row_number,
                )
            )
        if not row.shariah_cert_ref:
            report.errors.append(
                Finding(
                    "error",
                    "NO_SHARIAH_REFERENCE",
                    f"{row.holding_id}: every investment needs its Shariah approval reference",
                    row.row_number,
                )
            )
        if row.asset_class in (AssetClass.WAKALA, AssetClass.SUKUK):
            missing = [
                name
                for name, value in (
                    ("profit rate", row.profit_rate),
                    ("start date", row.start_date),
                    ("maturity date", row.maturity_date),
                )
                if value is None
            ]
            if missing and not row.is_placeholder:
                report.errors.append(
                    Finding(
                        "error",
                        "MISSING_TERMS",
                        f"{row.holding_id}: {', '.join(missing)} missing; mark the row as a "
                        "placeholder if the terms are still to come from the custodian",
                        row.row_number,
                    )
                )
            elif missing:
                report.warnings.append(
                    Finding(
                        "warning",
                        "PLACEHOLDER_TERMS",
                        f"{row.holding_id}: {', '.join(missing)} still pending from the "
                        "custodian; this holding will not accrue profit until its terms are "
                        "loaded (open decision 3)",
                        row.row_number,
                    )
                )
        if row.maturity_date is not None and row.maturity_date <= cutover:
            report.errors.append(
                Finding(
                    "error",
                    "MATURED_BEFORE_CUTOVER",
                    f"{row.holding_id}: matures {row.maturity_date.isoformat()}, on or before "
                    f"the cutover date {cutover.isoformat()}, so it is not held at cutover",
                    row.row_number,
                )
            )

    # --- journal lines ------------------------------------------------------
    codes = {line.account_code for line in batch.lines}
    accounts = {
        account.code: account
        for account in db.execute(select(Account).where(Account.code.in_(sorted(codes)))).scalars()
    }
    for line in batch.lines:
        account = accounts.get(line.account_code)
        if account is None:
            report.errors.append(
                Finding(
                    "error",
                    "UNKNOWN_ACCOUNT",
                    f"account {line.account_code} does not exist",
                    line.row_number,
                )
            )
            continue
        if not account.is_postable:
            report.errors.append(
                Finding(
                    "error",
                    "HEADING_ACCOUNT",
                    f"account {line.account_code} ({account.name}) is a heading",
                    line.row_number,
                )
            )
        if account.status is not RecordStatus.ACTIVE:
            report.errors.append(
                Finding(
                    "error",
                    "INACTIVE_ACCOUNT",
                    f"account {line.account_code} is {account.status}",
                    line.row_number,
                )
            )
        if account.type is AccountType.EQUITY:
            report.errors.append(
                Finding(
                    "error",
                    "EQUITY_ACCOUNT",
                    f"account {line.account_code} is firm equity; client money is a liability",
                    line.row_number,
                )
            )
        owner = owners.get(line.account_code)
        if owner is not None and owner != batch.client_id:
            report.errors.append(
                Finding(
                    "error",
                    "ACCOUNT_BELONGS_TO_ANOTHER_CLIENT",
                    f"account {line.account_code} belongs to {owner}",
                    line.row_number,
                )
            )
        if account.report == "PL" and not batch.include_pl:
            report.errors.append(
                Finding(
                    "error",
                    "PL_NOT_ALLOWED",
                    f"account {line.account_code} is a profit and loss account; this batch "
                    "loads client profit only (open decision 2)",
                    line.row_number,
                )
            )
        if account.needs_holding and not line.holding_id:
            if line.account_code == accrued_code and batch.pro_rata_accrual_split:
                continue  # handled by the pro-rata split below
            report.errors.append(
                Finding(
                    "error",
                    "HOLDING_REQUIRED",
                    f"account {line.account_code} ({account.name}) is a sub-ledger account and "
                    "needs a holding; accrued profit must be loaded per holding"
                    + (
                        ""
                        if line.account_code != accrued_code
                        else ", or request the pro-rata placeholder split"
                    ),
                    line.row_number,
                )
            )
        if line.holding_id and line.holding_id not in holdings_by_id:
            report.errors.append(
                Finding(
                    "error",
                    "UNKNOWN_HOLDING",
                    f"line references holding {line.holding_id}, which is not in holdings.csv",
                    line.row_number,
                )
            )
        if account.currency and account.currency != line.currency:
            report.errors.append(
                Finding(
                    "error",
                    "ACCOUNT_CURRENCY",
                    f"account {line.account_code} is a {account.currency} account but the line "
                    f"is {line.currency}",
                    line.row_number,
                )
            )

    # --- pro-rata placeholder split -----------------------------------------
    _apply_pro_rata_split(db, batch, report, accrued_code=accrued_code)
    db.flush()
    db.refresh(batch)

    # --- investment line per holding ----------------------------------------
    for row in batch.holdings:
        expected_code = _investment_account(db, batch, row)
        if expected_code is None:
            continue
        booked = money(
            sum(
                (
                    line.signed
                    for line in batch.lines
                    if line.holding_id == row.holding_id and line.account_code == expected_code
                ),
                Decimal(0),
            )
        )
        if booked != row.face_amount:
            report.errors.append(
                Finding(
                    "error",
                    "INVESTMENT_LINE_MISMATCH",
                    f"{row.holding_id}: {expected_code} carries {booked:.2f} but the holding's "
                    f"cost is {row.face_amount:.2f}",
                    row.row_number,
                )
            )

    # --- balance per currency and in base -----------------------------------
    client = db.get(Client, batch.client_id)
    assert client is not None
    per_currency: dict[str, Decimal] = {}
    base_total = ZERO
    for line in batch.lines:
        per_currency[line.currency] = money(per_currency.get(line.currency, ZERO) + line.signed)
    for currency, total in sorted(per_currency.items()):
        if total != 0:
            report.errors.append(
                Finding(
                    "error",
                    "UNBALANCED",
                    f"{currency} debits and credits differ by {total:+.2f}",
                )
            )
    try:
        for line in batch.lines:
            rate = fx_rates.rate_for(db, line.currency, client.base_currency, cutover)
            base_total = money(base_total + money(line.signed * rate))
        if base_total != 0:
            report.errors.append(
                Finding(
                    "error",
                    "UNBALANCED_BASE",
                    f"base currency amounts differ by {base_total:+.2f} {client.base_currency} "
                    f"at the {cutover.isoformat()} rate",
                )
            )
    except Exception as exc:  # missing rate
        report.errors.append(Finding("error", "MISSING_FX_RATE", str(exc)))

    # --- reasonableness of the opening accrued profit -----------------------
    settings = get_settings()
    for row in batch.holdings:
        expected = expected_accrual(row, cutover)
        if expected is None:
            continue
        loaded = money(
            sum(
                (
                    line.signed
                    for line in batch.lines
                    if line.holding_id == row.holding_id and line.account_code == accrued_code
                ),
                Decimal(0),
            )
        )
        difference = money(loaded - expected)
        tolerance = max(
            round_money(expected * settings.accrual_tolerance_pct), settings.accrual_tolerance_abs
        )
        if abs(difference) > tolerance:
            report.warnings.append(
                Finding(
                    "warning",
                    "ACCRUAL_OUT_OF_TOLERANCE",
                    f"{row.holding_id}: opening accrued profit {loaded:.2f} differs from the "
                    f"recomputed {expected:.2f} by {difference:+.2f} (tolerance "
                    f"{tolerance:.2f})",
                    row.row_number,
                )
            )

    # --- A = B, and the suspense escape hatch -------------------------------
    section_a, section_b, suspense = _ab_check(db, batch)
    report.totals.update(
        {
            "debits": f"{money(sum((line.debit for line in batch.lines), Decimal(0))):.2f}",
            "credits": f"{money(sum((line.credit for line in batch.lines), Decimal(0))):.2f}",
            "section_a": f"{section_a:.2f}",
            "section_b": f"{section_b:.2f}",
            "suspense": f"{suspense:.2f}",
        }
    )
    if section_a != section_b:
        report.errors.append(
            Finding(
                "error",
                "AB_MISMATCH",
                f"client capital and profit of {section_a:.2f} do not equal net assets of "
                f"{section_b:.2f}; put the {money(section_a - section_b):+.2f} difference on "
                "suspense (1390) with a reason, or correct the figures",
            )
        )
    elif suspense != 0:
        reasons = [
            line.description
            for line in batch.lines
            if line.account_code == resolve(db, batch.client_id, SUSPENSE_ROLE)
        ]
        if not any(reason.strip() for reason in reasons):
            report.errors.append(
                Finding(
                    "error",
                    "SUSPENSE_WITHOUT_REASON",
                    f"{suspense:.2f} is on suspense (1390) without a reason",
                )
            )
        else:
            report.warnings.append(
                Finding(
                    "warning",
                    "SUSPENSE_BALANCE",
                    f"{suspense:.2f} is unreconciled and sits on suspense (1390): "
                    f"{'; '.join(r for r in reasons if r.strip())}. Statements for this client "
                    "are held until a correcting entry clears it (open decision 4)",
                )
            )

    # --- custodian check ----------------------------------------------------
    _custodian_check(db, batch, report)

    return _finish(db, batch, report)


def _apply_pro_rata_split(
    db: Session, batch: OpeningBalanceBatch, report: ValidationReport, *, accrued_code: str
) -> None:
    """Split a total accrued profit figure across holdings, as a labelled placeholder."""
    totals = [
        line
        for line in batch.lines
        if line.account_code == accrued_code and not line.holding_id and not line.derived
    ]
    if not totals:
        return
    if not batch.pro_rata_accrual_split:
        return

    candidates = [
        row for row in batch.holdings if row.profit_rate is not None and row.face_amount > 0
    ] or [row for row in batch.holdings if row.face_amount > 0]
    if not candidates:
        report.errors.append(
            Finding(
                "error",
                "NO_SPLIT_CANDIDATES",
                "there are no holdings to split the accrued profit across",
            )
        )
        return

    for total_line in totals:
        amount = total_line.signed
        weights = [
            (row.face_amount * (row.profit_rate or Decimal(1)) / Decimal(row.day_basis))
            for row in candidates
        ]
        parts = split_pro_rata(amount, weights)
        for row, part in zip(candidates, parts, strict=True):
            if part == 0:
                continue
            db.add(
                OpeningBalanceLine(
                    batch_id=batch.id,
                    row_number=total_line.row_number,
                    account_code=accrued_code,
                    holding_id=row.holding_id,
                    currency=total_line.currency,
                    debit=part if part > 0 else ZERO,
                    credit=-part if part < 0 else ZERO,
                    description=(
                        f"PLACEHOLDER pro-rata share of {amount:.2f} accrued profit "
                        f"({total_line.description})"
                    ),
                    derived=True,
                    created_by=batch.prepared_by,
                )
            )
        db.delete(total_line)
        report.warnings.append(
            Finding(
                "warning",
                "PRO_RATA_ACCRUAL_PLACEHOLDER",
                f"{amount:.2f} of accrued profit has been split across "
                f"{len(candidates)} holdings pro-rata to daily profit. This is a clearly "
                "labelled placeholder: the per-holding figures must be confirmed with the "
                "custodian (open decision 3)",
                total_line.row_number,
            )
        )


def _ab_check(db: Session, batch: OpeningBalanceBatch) -> tuple[Decimal, Decimal, Decimal]:
    """Section A (capital + profit), Section B (assets - payables) and suspense."""
    capital_code = resolve(db, batch.client_id, Role.CLIENT_CAPITAL)
    profit_code = resolve(db, batch.client_id, Role.CLIENT_PROFIT)
    suspense_code = resolve(db, batch.client_id, SUSPENSE_ROLE)
    codes = {line.account_code for line in batch.lines}
    accounts = {
        account.code: account
        for account in db.execute(select(Account).where(Account.code.in_(sorted(codes)))).scalars()
    }

    section_a = ZERO
    assets = ZERO
    payables = ZERO
    suspense = ZERO
    pl = ZERO
    for line in batch.lines:
        account = accounts.get(line.account_code)
        if account is None:
            continue
        if line.account_code in (capital_code, profit_code):
            section_a = money(section_a - line.signed)
        elif account.type is AccountType.ASSET:
            assets = money(assets + line.signed)
        elif account.type is AccountType.LIABILITY:
            payables = money(payables - line.signed)
        else:
            pl = money(pl + line.signed)
        if line.account_code == suspense_code:
            suspense = money(suspense + line.signed)
    # A profit and loss opening load reduces client profit by the same net amount, so
    # the un-closed result belongs in section A too.
    section_a = money(section_a - pl)
    return section_a, money(assets - payables), suspense


def _custodian_check(db: Session, batch: OpeningBalanceBatch, report: ValidationReport) -> None:
    rows = list(
        db.execute(
            select(OpeningCustodianRow).where(OpeningCustodianRow.batch_id == batch.id)
        ).scalars()
    )
    balance_rows = {row.key: row for row in rows if row.kind == "BALANCE"}
    position_rows = {row.key: row for row in rows if row.kind == "POSITION"}

    cash_by_account: dict[str, Decimal] = {}
    for account in db.execute(
        select(CustodyAccount).where(CustodyAccount.client_id == batch.client_id)
    ).scalars():
        total = money(
            sum(
                (
                    line.signed
                    for line in batch.lines
                    if line.account_code == account.cash_ledger_code
                    and line.currency == account.currency
                ),
                Decimal(0),
            )
        )
        if total != 0 or account.id in balance_rows or account.account_number in balance_rows:
            cash_by_account[account.id] = total

    for account_id, ledger in cash_by_account.items():
        custody = db.get(CustodyAccount, account_id)
        assert custody is not None
        row = balance_rows.get(account_id) or balance_rows.get(custody.account_number)
        if row is None:
            report.errors.append(
                Finding(
                    "error",
                    "NO_CUSTODIAN_BALANCE",
                    f"custody account {custody.account_number} has {ledger:.2f} loaded but no "
                    "custodian statement balance was supplied",
                )
            )
            continue
        if row.as_of != batch.cutover_date:
            report.errors.append(
                Finding(
                    "error",
                    "CUSTODIAN_BALANCE_DATE",
                    f"custodian balance for {custody.account_number} is as at "
                    f"{row.as_of.isoformat()}, not the cutover date "
                    f"{batch.cutover_date.isoformat()}",
                )
            )
        if row.amount != ledger:
            report.errors.append(
                Finding(
                    "error",
                    "CUSTODIAN_BALANCE_MISMATCH",
                    f"custody account {custody.account_number}: loaded {ledger:.2f} but the "
                    f"custodian reports {row.amount:.2f}",
                )
            )

    for holding_row in batch.holdings:
        row = position_rows.get(holding_row.holding_id)
        if row is None:
            report.errors.append(
                Finding(
                    "error",
                    "NO_CUSTODIAN_POSITION",
                    f"{holding_row.holding_id}: no custodian position was supplied",
                    holding_row.row_number,
                )
            )
            continue
        expected = (
            holding_row.nominal
            if holding_row.asset_class is AssetClass.SUKUK and holding_row.nominal
            else holding_row.face_amount
        )
        if row.amount != expected:
            report.errors.append(
                Finding(
                    "error",
                    "CUSTODIAN_POSITION_MISMATCH",
                    f"{holding_row.holding_id}: loaded {expected:.2f} but the custodian reports "
                    f"{row.amount:.2f}",
                    holding_row.row_number,
                )
            )

    for key in position_rows:
        if key not in {row.holding_id for row in batch.holdings}:
            report.errors.append(
                Finding(
                    "error",
                    "UNKNOWN_CUSTODIAN_POSITION",
                    f"the custodian reports a position in {key}, which is not in holdings.csv",
                )
            )


def _finish(db: Session, batch: OpeningBalanceBatch, report: ValidationReport) -> ValidationReport:
    batch.validation_report = report.as_dict()
    batch.status = BatchStatus.VALIDATED if report.ok else BatchStatus.DRAFT
    if report.warnings:
        batch.warnings_acknowledged_by = None
        batch.warnings_acknowledged_note = None
    db.flush()
    audit.record(
        db,
        user_id=batch.prepared_by,
        action="OPENING_BATCH_VALIDATED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=batch.client_id,
        detail={
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "totals": report.totals,
        },
    )
    return report


def acknowledge_warnings(
    db: Session, batch: OpeningBalanceBatch, *, user_id: str, note: str
) -> None:
    if batch.status is not BatchStatus.VALIDATED:
        raise Conflict(f"batch {batch.id} is {batch.status}", status=str(batch.status))
    if not note.strip():
        raise BusinessRule("acknowledging the warnings needs a written note")
    batch.warnings_acknowledged_by = user_id
    batch.warnings_acknowledged_note = note
    db.flush()
    audit.record(
        db,
        user_id=user_id,
        action="OPENING_BATCH_WARNINGS_ACKNOWLEDGED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=batch.client_id,
        detail={"note": note},
    )


def submit(db: Session, batch: OpeningBalanceBatch, *, user_id: str) -> OpeningBalanceBatch:
    if batch.status is not BatchStatus.VALIDATED:
        raise Conflict(
            f"batch {batch.id} must pass validation before it is submitted",
            status=str(batch.status),
        )
    report = batch.validation_report or {}
    if report.get("warnings") and not batch.warnings_acknowledged_by:
        raise BusinessRule(
            "the validation warnings must be acknowledged in writing before submission",
            warnings=len(report.get("warnings", [])),
        )
    batch.status = BatchStatus.SUBMITTED
    batch.submitted_at = utcnow()
    db.flush()
    audit.record(
        db,
        user_id=user_id,
        action="OPENING_BATCH_SUBMITTED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=batch.client_id,
        detail={"cutover_date": batch.cutover_date.isoformat()},
    )
    return batch


def reject(
    db: Session, batch: OpeningBalanceBatch, *, approver: User, reason: str
) -> OpeningBalanceBatch:
    _assert_approver(batch, approver)
    if batch.status is not BatchStatus.SUBMITTED:
        raise Conflict(f"batch {batch.id} is {batch.status}", status=str(batch.status))
    if not reason.strip():
        raise BusinessRule("a rejection needs a reason")
    batch.status = BatchStatus.REJECTED
    batch.rejection_reason = reason
    batch.approved_by = approver.id
    batch.approved_at = utcnow()
    db.flush()
    audit.record(
        db,
        user_id=approver.id,
        action="OPENING_BATCH_REJECTED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=batch.client_id,
        detail={"reason": reason},
    )
    return batch


def _assert_approver(batch: OpeningBalanceBatch, approver: User) -> None:
    if approver.role not in (UserRole.FINANCE, UserRole.SIGNATORY):
        raise MakerCheckerBreach(
            "an opening balance batch is approved by finance or an authorised signatory",
            role=str(approver.role),
        )


@dataclass
class PostResult:
    batch: OpeningBalanceBatch
    entry: JournalEntry
    holdings_created: int
    reconciliation: recon_svc.ReconResult
    locked_through: date


def approve(db: Session, batch: OpeningBalanceBatch, *, approver: User) -> PostResult:
    """Approve and post the batch, in one transaction."""
    _assert_approver(batch, approver)
    if batch.status is not BatchStatus.SUBMITTED:
        raise Conflict(
            f"batch {batch.id} is {batch.status}; only a submitted batch can be approved",
            status=str(batch.status),
        )

    client = db.get(Client, batch.client_id)
    assert client is not None
    cutover = batch.cutover_date
    accrued_code = resolve(db, batch.client_id, ACCRUED_ROLE)

    # 1. the holdings, with their accrual continuity
    created = 0
    for row in batch.holdings:
        custody = _custody_account(db, batch, row.custody_account)
        assert custody is not None
        opening_accrued = money(
            sum(
                (
                    line.signed
                    for line in batch.lines
                    if line.holding_id == row.holding_id and line.account_code == accrued_code
                ),
                Decimal(0),
            )
        )
        db.add(
            Holding(
                id=row.holding_id,
                client_id=batch.client_id,
                asset_class=row.asset_class,
                custody_account_id=custody.id,
                currency=row.currency,
                counterparty=row.counterparty,
                description=row.description,
                face_amount=row.face_amount,
                nominal=row.nominal,
                profit_rate=row.profit_rate,
                day_basis=row.day_basis,
                start_date=row.start_date,
                maturity_date=row.maturity_date,
                monthly_rent=row.monthly_rent,
                accrual_start=cutover + timedelta(days=1),
                opening_accrued=opening_accrued,
                opening_batch_id=batch.id,
                shariah_cert_ref=row.shariah_cert_ref,
                external_ref=row.external_ref,
                is_placeholder=row.is_placeholder,
                status=HoldingStatus.ACTIVE,
                created_by=approver.id,
            )
        )
        created += 1
    db.flush()

    # 2. one OPENING_BALANCE entry dated the cutover date
    drafts = [
        LineDraft(
            account_code=line.account_code,
            amount=line.signed,
            client_id=batch.client_id,
            holding_id=line.holding_id,
            currency=line.currency,
            description=line.description,
        )
        for line in batch.lines
    ]
    currencies = {line.currency for line in batch.lines}
    entry = post(
        db,
        entry_date=cutover,
        event=LedgerEvent.OPENING_BALANCE,
        client_id=batch.client_id,
        currency=client.base_currency if len(currencies) > 1 else next(iter(currencies)),
        lines=drafts,
        narrative=(
            f"Opening balances as at close of business {cutover.isoformat()}, batch {batch.id}"
        ),
        reference=f"OB/{batch.client_id}/{cutover.isoformat()}",
        batch_id=batch.id,
        created_by=approver.id,
        multi_currency=len(currencies) > 1,
    )

    # 3. the custodian's own figures, for the reconciliation
    for custodian_row in db.execute(
        select(OpeningCustodianRow).where(OpeningCustodianRow.batch_id == batch.id)
    ).scalars():
        if custodian_row.kind == "BALANCE":
            custody = _custody_account(db, batch, custodian_row.key)
            assert custody is not None
            recon_svc.record_balance(
                db,
                custody_account_id=custody.id,
                as_of=custodian_row.as_of,
                balance=custodian_row.amount,
                statement_ref=custodian_row.statement_ref,
                recorded_by=approver.id,
            )
        else:
            recon_svc.record_position(
                db,
                holding_id=custodian_row.key,
                as_of=custodian_row.as_of,
                amount=custodian_row.amount,
                statement_ref=custodian_row.statement_ref,
                recorded_by=approver.id,
            )

    # 4. reconcile at the cutover date
    reconciliation = recon_svc.run(
        db, as_of=cutover, performed_by=approver.id, client_id=batch.client_id
    )

    batch.status = BatchStatus.POSTED
    batch.approved_by = approver.id
    batch.approved_at = utcnow()
    batch.journal_entry_id = entry.id
    db.flush()

    audit.record(
        db,
        user_id=approver.id,
        action="OPENING_BATCH_POSTED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=batch.client_id,
        detail={
            "cutover_date": cutover.isoformat(),
            "journal_entry_id": entry.id,
            "holdings_created": created,
            "reconciliation_run_id": reconciliation.run_id,
            "reconciliation_breaks": len(reconciliation.breaks),
            "locked_through": cutover.isoformat(),
        },
    )
    return PostResult(
        batch=batch,
        entry=entry,
        holdings_created=created,
        reconciliation=reconciliation,
        locked_through=cutover,
    )


# --- Preview -----------------------------------------------------------------


@dataclass
class PreviewLine:
    account_code: str
    account_name: str
    holding_id: str | None
    currency: str
    debit: Decimal
    credit: Decimal
    description: str
    derived: bool


@dataclass
class Preview:
    batch_id: int
    client_id: str
    cutover_date: date
    lines: list[PreviewLine]
    total_debit: Decimal
    total_credit: Decimal
    section_a: Decimal
    section_b: Decimal
    suspense: Decimal
    holdings: list[dict[str, Any]]
    validation: dict[str, Any]

    @property
    def balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def reconciles(self) -> bool:
        return self.section_a == self.section_b


def preview(db: Session, batch: OpeningBalanceBatch) -> Preview:
    codes = {line.account_code for line in batch.lines}
    names = dict(
        db.execute(select(Account.code, Account.name).where(Account.code.in_(sorted(codes)))).all()
    )
    lines = [
        PreviewLine(
            account_code=line.account_code,
            account_name=names.get(line.account_code, "<unknown account>"),
            holding_id=line.holding_id,
            currency=line.currency,
            debit=line.debit,
            credit=line.credit,
            description=line.description,
            derived=line.derived,
        )
        for line in sorted(batch.lines, key=lambda line: (line.account_code, line.row_number))
    ]
    section_a, section_b, suspense = _ab_check(db, batch)
    return Preview(
        batch_id=batch.id,
        client_id=batch.client_id,
        cutover_date=batch.cutover_date,
        lines=lines,
        total_debit=money(sum((line.debit for line in lines), Decimal(0))),
        total_credit=money(sum((line.credit for line in lines), Decimal(0))),
        section_a=section_a,
        section_b=section_b,
        suspense=suspense,
        holdings=[
            {
                "holding_id": row.holding_id,
                "asset_class": str(row.asset_class),
                "currency": row.currency,
                "counterparty": row.counterparty,
                "face_amount": f"{row.face_amount:.2f}",
                "profit_rate": None if row.profit_rate is None else f"{row.profit_rate:f}",
                "maturity_date": None
                if row.maturity_date is None
                else row.maturity_date.isoformat(),
                "is_placeholder": row.is_placeholder,
                "expected_accrual": _money_or_none(expected_accrual(row, batch.cutover_date)),
            }
            for row in batch.holdings
        ],
        validation=batch.validation_report or {},
    )


def get_batch(db: Session, batch_id: int) -> OpeningBalanceBatch:
    batch = db.get(OpeningBalanceBatch, batch_id)
    if batch is None:
        raise NotFound(f"unknown opening balance batch {batch_id}", batch_id=batch_id)
    return batch


def delete_batch(db: Session, batch: OpeningBalanceBatch, *, user_id: str) -> None:
    """Discard a batch that has not reached the ledger.

    Nothing here has touched the ledger until POSTED (see _editable()), so up to
    that point a batch is just staged CSV rows -- safe to throw away and start
    over. The custodian rows have no ORM relationship on the batch (only the
    holdings and lines do, which cascade), so they are deleted explicitly first.
    """
    _editable(batch)
    for row in db.execute(
        select(OpeningCustodianRow).where(OpeningCustodianRow.batch_id == batch.id)
    ).scalars():
        db.delete(row)
    audit.record(
        db,
        user_id=user_id,
        action="OPENING_BATCH_DELETED",
        entity="opening_balance_batch",
        entity_id=batch.id,
        client_id=batch.client_id,
        detail={"status": str(batch.status), "cutover_date": batch.cutover_date.isoformat()},
    )
    db.delete(batch)
    db.flush()


def list_batches(db: Session, *, client_id: str | None = None) -> list[OpeningBalanceBatch]:
    stmt = select(OpeningBalanceBatch).order_by(OpeningBalanceBatch.id.desc())
    if client_id:
        stmt = stmt.where(OpeningBalanceBatch.client_id == client_id)
    return list(db.execute(stmt).scalars())


def template(name: str) -> str:
    if name not in TEMPLATES:
        raise NotFound(f"unknown template {name!r}", name=name)
    return TEMPLATES[name]

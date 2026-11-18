"""Posting roles and how they resolve to account codes.

Business code never names an account code.  It asks for a *role* -- ``CLIENT_CAPITAL``,
``ACCRUED_INCOME`` -- and the role mapping table resolves it per client.  Account codes
appear only in seed data, configuration and this module's resolution logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BusinessRule, NotFound
from app.models import AssetClass, CustodyAccount, RoleMapping


class Role(StrEnum):
    # Resolved from the custody account, not from the role mapping table
    BANK = "BANK"
    BANK_FROM = "BANK_FROM"
    BANK_TO = "BANK_TO"

    # Resolved from the holding's asset class
    INVESTMENT = "INVESTMENT"
    INCOME = "INCOME"
    FEE_EXPENSE = "FEE_EXPENSE"
    FV_ADJUSTMENT = "FV_ADJUSTMENT"

    # Client-owned
    CLIENT_CAPITAL = "CLIENT_CAPITAL"
    CLIENT_PROFIT = "CLIENT_PROFIT"

    # Investments
    WAKALA = "WAKALA"
    SUKUK = "SUKUK"
    SUKUK_FV_ADJUSTMENT = "SUKUK_FV_ADJUSTMENT"
    COMMODITY_MURABAHA = "COMMODITY_MURABAHA"
    PRIVATE_FINANCING = "PRIVATE_FINANCING"
    INVESTMENT_PROPERTY = "INVESTMENT_PROPERTY"
    PROPERTY_FV_ADJUSTMENT = "PROPERTY_FV_ADJUSTMENT"

    # Receivables and payables
    ACCRUED_INCOME = "ACCRUED_INCOME"
    ACCOUNTS_RECEIVABLE = "ACCOUNTS_RECEIVABLE"
    RENT_RECEIVABLE = "RENT_RECEIVABLE"
    SUSPENSE = "SUSPENSE"
    ACCOUNTS_PAYABLE = "ACCOUNTS_PAYABLE"
    MGMT_FEE_PAYABLE = "MGMT_FEE_PAYABLE"
    CUSTODY_FEE_PAYABLE = "CUSTODY_FEE_PAYABLE"
    WHT_FINAL_PAYABLE = "WHT_FINAL_PAYABLE"
    RENT_DEPOSITS = "RENT_DEPOSITS"

    # Income
    WAKALA_INCOME = "WAKALA_INCOME"
    PRIVATE_FINANCING_INCOME = "PRIVATE_FINANCING_INCOME"
    RENTAL_INCOME = "RENTAL_INCOME"
    SUKUK_INCOME = "SUKUK_INCOME"
    FX_GAIN = "FX_GAIN"
    FV_GAIN = "FV_GAIN"

    # Expense
    WAKALA_FEE_EXPENSE = "WAKALA_FEE_EXPENSE"
    PRIVATE_FINANCING_FEE_EXPENSE = "PRIVATE_FINANCING_FEE_EXPENSE"
    RENTAL_FEE_EXPENSE = "RENTAL_FEE_EXPENSE"
    SUKUK_FEE_EXPENSE = "SUKUK_FEE_EXPENSE"
    WHT_AT_SOURCE = "WHT_AT_SOURCE"
    CUSTODY_FEE_EXPENSE = "CUSTODY_FEE_EXPENSE"
    FX_LOSS = "FX_LOSS"
    FINANCING_WRITE_OFF = "FINANCING_WRITE_OFF"
    FV_LOSS = "FV_LOSS"


BANK_ROLES = frozenset({Role.BANK, Role.BANK_FROM, Role.BANK_TO})
CLASS_DERIVED_ROLES = frozenset(
    {Role.INVESTMENT, Role.INCOME, Role.FEE_EXPENSE, Role.FV_ADJUSTMENT}
)


@dataclass(frozen=True)
class AssetClassRoles:
    investment: Role
    income: Role
    fee_expense: Role
    fv_adjustment: Role | None


ASSET_CLASS_ROLES: dict[AssetClass, AssetClassRoles] = {
    AssetClass.WAKALA: AssetClassRoles(
        investment=Role.WAKALA,
        income=Role.WAKALA_INCOME,
        fee_expense=Role.WAKALA_FEE_EXPENSE,
        fv_adjustment=None,
    ),
    AssetClass.SUKUK: AssetClassRoles(
        investment=Role.SUKUK,
        income=Role.SUKUK_INCOME,
        fee_expense=Role.SUKUK_FEE_EXPENSE,
        fv_adjustment=Role.SUKUK_FV_ADJUSTMENT,
    ),
    AssetClass.PRIVATE_FINANCING: AssetClassRoles(
        investment=Role.PRIVATE_FINANCING,
        income=Role.PRIVATE_FINANCING_INCOME,
        fee_expense=Role.PRIVATE_FINANCING_FEE_EXPENSE,
        fv_adjustment=None,
    ),
    AssetClass.PROPERTY: AssetClassRoles(
        investment=Role.INVESTMENT_PROPERTY,
        income=Role.RENTAL_INCOME,
        fee_expense=Role.RENTAL_FEE_EXPENSE,
        fv_adjustment=Role.PROPERTY_FV_ADJUSTMENT,
    ),
}


def class_role(asset_class: AssetClass, role: Role) -> Role:
    """Resolve ``{INVESTMENT}``, ``{INCOME}``, ``{FEE_EXPENSE}``, ``{FV_ADJUSTMENT}``."""
    mapping = ASSET_CLASS_ROLES[asset_class]
    match role:
        case Role.INVESTMENT:
            return mapping.investment
        case Role.INCOME:
            return mapping.income
        case Role.FEE_EXPENSE:
            return mapping.fee_expense
        case Role.FV_ADJUSTMENT:
            if mapping.fv_adjustment is None:
                raise BusinessRule(
                    f"{asset_class} holdings are not carried at fair value",
                    asset_class=str(asset_class),
                )
            return mapping.fv_adjustment
        case _:  # pragma: no cover - callers filter first
            return role


def resolve(
    db: Session,
    client_id: str,
    role: Role | str,
    *,
    custody_account: CustodyAccount | None = None,
    asset_class: AssetClass | None = None,
) -> str:
    """Resolve *role* to an account code for *client_id*.

    Client-specific mappings win over the ``*`` fallback.  Cash and Wakala deposit
    accounts come from the custody account, which is where the custodian relationship
    is recorded.
    """
    role_enum = Role(role)

    if role_enum in CLASS_DERIVED_ROLES:
        if asset_class is None:
            raise BusinessRule(f"role {role_enum} needs a holding to resolve", role=str(role_enum))
        role_enum = class_role(asset_class, role_enum)

    if role_enum in BANK_ROLES:
        if custody_account is None:
            raise BusinessRule(
                f"role {role_enum} needs a custody account to resolve", role=str(role_enum)
            )
        return custody_account.cash_ledger_code

    if role_enum is Role.WAKALA and custody_account is not None:
        return custody_account.wakala_ledger_code

    candidates = dict(
        db.execute(
            select(RoleMapping.client_id, RoleMapping.account_code)
            .where(RoleMapping.role == str(role_enum))
            .where(RoleMapping.client_id.in_([client_id, "*"]))
        ).all()
    )
    code = candidates.get(client_id) or candidates.get("*")
    if code is None:
        raise NotFound(
            f"no account mapped to role {role_enum} for client {client_id}",
            role=str(role_enum),
            client_id=client_id,
        )
    return code


def client_owned_accounts(db: Session) -> dict[str, str]:
    """Map account code -> owning client id.

    An account owned by a client (its capital, its profit and its custody cash
    accounts) can only take that client's journal lines.  An account reachable from
    more than one client is shared and therefore not owned by any of them.
    """
    owners: dict[str, set[str]] = {}

    for client_id, code in db.execute(
        select(RoleMapping.client_id, RoleMapping.account_code).where(
            RoleMapping.role.in_([str(Role.CLIENT_CAPITAL), str(Role.CLIENT_PROFIT)]),
            RoleMapping.client_id != "*",
        )
    ):
        owners.setdefault(code, set()).add(client_id)

    for client_id, code in db.execute(
        select(CustodyAccount.client_id, CustodyAccount.cash_ledger_code)
    ):
        owners.setdefault(code, set()).add(client_id)

    return {code: next(iter(ids)) for code, ids in owners.items() if len(ids) == 1}

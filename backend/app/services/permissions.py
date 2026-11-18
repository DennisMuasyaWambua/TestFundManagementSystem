"""The permission table from section 9, as data.

Permissions are enforced in the API.  The frontend only *hides* what a user cannot do;
it never decides.  The 401/403 contract test is generated directly from this table so
the two can never drift apart.

ADMIN has no money powers at all: it manages users and nothing else.
"""

from __future__ import annotations

from enum import StrEnum

from app.errors import PermissionDenied
from app.models import User, UserRole

M, S, F, C, A = (
    UserRole.MAKER,
    UserRole.SIGNATORY,
    UserRole.FINANCE,
    UserRole.COMPLIANCE,
    UserRole.ADMIN,
)


class Permission(StrEnum):
    INSTRUCTION_CREATE = "INSTRUCTION_CREATE"
    INSTRUCTION_APPROVE = "INSTRUCTION_APPROVE"
    INSTRUCTION_DISPATCH = "INSTRUCTION_DISPATCH"
    RECEIPT_RECORD = "RECEIPT_RECORD"
    LEDGER_OPERATIONS = "LEDGER_OPERATIONS"
    VALUATION_PROPOSE = "VALUATION_PROPOSE"
    VALUATION_APPROVE = "VALUATION_APPROVE"
    OPENING_BALANCE_PREPARE = "OPENING_BALANCE_PREPARE"
    OPENING_BALANCE_APPROVE = "OPENING_BALANCE_APPROVE"
    CUSTODIAN_STATEMENT_RECORD = "CUSTODIAN_STATEMENT_RECORD"
    RECONCILIATION_RUN = "RECONCILIATION_RUN"
    REPORTS_VIEW = "REPORTS_VIEW"
    AUDIT_VIEW = "AUDIT_VIEW"
    USERS_MANAGE = "USERS_MANAGE"
    CLIENT_ONBOARDING = "CLIENT_ONBOARDING"
    JOURNAL_VIEW = "JOURNAL_VIEW"
    FX_RATES_MANAGE = "FX_RATES_MANAGE"


PERMISSIONS: dict[Permission, frozenset[UserRole]] = {
    Permission.INSTRUCTION_CREATE: frozenset({M}),
    Permission.INSTRUCTION_APPROVE: frozenset({S}),
    Permission.INSTRUCTION_DISPATCH: frozenset({M, F}),
    Permission.RECEIPT_RECORD: frozenset({M, F}),
    Permission.LEDGER_OPERATIONS: frozenset({F}),
    Permission.VALUATION_PROPOSE: frozenset({M, F}),
    Permission.VALUATION_APPROVE: frozenset({F, S}),
    Permission.OPENING_BALANCE_PREPARE: frozenset({F}),
    Permission.OPENING_BALANCE_APPROVE: frozenset({F, S}),
    Permission.CUSTODIAN_STATEMENT_RECORD: frozenset({F, C}),
    # CoB reg 29(5)-(7): the reconciliation may not be run by a payment signatory.
    Permission.RECONCILIATION_RUN: frozenset({F, C}),
    Permission.REPORTS_VIEW: frozenset({M, S, F, C}),
    Permission.AUDIT_VIEW: frozenset({C, A}),
    Permission.USERS_MANAGE: frozenset({A}),
    Permission.CLIENT_ONBOARDING: frozenset({F, C}),
    Permission.JOURNAL_VIEW: frozenset({F, C}),
    Permission.FX_RATES_MANAGE: frozenset({F}),
}


def allows(role: UserRole, permission: Permission) -> bool:
    return role in PERMISSIONS[permission]


def permissions_for(role: UserRole) -> list[str]:
    return sorted(str(p) for p in Permission if allows(role, p))


def require(user: User, permission: Permission) -> None:
    if not allows(user.role, permission):
        raise PermissionDenied(
            f"role {user.role} may not {permission}",
            role=str(user.role),
            permission=str(permission),
        )

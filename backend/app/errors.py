"""The single error shape used by the whole API.

Every business rule failure raises an :class:`AppError` subclass carrying a stable
machine-readable ``code``, a human message and optional ``details``.  The FastAPI
exception handler in ``app.main`` renders them as
``{"error": {"code": ..., "message": ..., "details": {...}}}``.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "INTERNAL_ERROR"
    status = 500

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = {k: v for k, v in details.items() if v is not None}

    def payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotAuthenticated(AppError):
    code = "NOT_AUTHENTICATED"
    status = 401


class MfaRequired(NotAuthenticated):
    """The password was right; this role must also present a one-time code.

    A subclass of :class:`NotAuthenticated` so it is still a 401 and still caught by
    anything handling failed authentication, but it carries its own code so the
    sign-in screen can show the authenticator step instead of an error.  It says
    nothing about whether the password matched, so it leaks nothing to an attacker
    who does not already hold valid credentials.
    """

    code = "MFA_REQUIRED"


class PermissionDenied(AppError):
    code = "PERMISSION_DENIED"
    status = 403


class NotFound(AppError):
    code = "NOT_FOUND"
    status = 404


class Conflict(AppError):
    """State conflict: wrong workflow state, duplicate, or a stale version."""

    code = "CONFLICT"
    status = 409


class BusinessRule(AppError):
    """A rule in the build specification was broken."""

    code = "BUSINESS_RULE"
    status = 422


# --- Specific business rules (stable codes the frontend can branch on) --------


class UnbalancedEntry(BusinessRule):
    code = "UNBALANCED_ENTRY"


class PeriodLocked(BusinessRule):
    code = "PERIOD_LOCKED"


class MissingFxRate(BusinessRule):
    code = "MISSING_FX_RATE"


class AccountNotPostable(BusinessRule):
    code = "ACCOUNT_NOT_POSTABLE"


class SegregationBreach(BusinessRule):
    code = "SEGREGATION_BREACH"


class HoldingRequired(BusinessRule):
    code = "HOLDING_REQUIRED"


class InsufficientCash(BusinessRule):
    code = "INSUFFICIENT_CASH"


class OnboardingIncomplete(BusinessRule):
    code = "ONBOARDING_INCOMPLETE"


class MakerCheckerBreach(BusinessRule):
    code = "MAKER_CHECKER_BREACH"


class ValidationFailed(BusinessRule):
    code = "VALIDATION_FAILED"


class LedgerImmutable(AppError):
    code = "LEDGER_IMMUTABLE"
    status = 409

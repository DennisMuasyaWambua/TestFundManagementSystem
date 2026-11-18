"""Authentication: policy, lockout, MFA, token revocation and the service account."""

from __future__ import annotations

from datetime import timedelta

import pyotp
import pytest
from app.config import get_settings
from app.errors import BusinessRule, MfaRequired, NotAuthenticated
from app.models import SYSTEM_USER, AuditLog, User, UserRole, utcnow
from app.services import auth as auth_svc
from sqlalchemy.orm import Session

from tests.conftest import TEST_PASSWORD


def test_password_policy_rejects_weak_passwords() -> None:
    for weak in ("short1!A", "alllowercase1!", "ALLUPPERCASE1!", "NoSymbols123", "No-Digits!!"):
        with pytest.raises(BusinessRule):
            auth_svc.check_password_policy(weak)
    auth_svc.check_password_policy("Str0ng-Enough!2026")


def test_generated_temporary_passwords_meet_the_policy() -> None:
    for _ in range(20):
        auth_svc.check_password_policy(auth_svc.temporary_password())


def test_login_succeeds_and_audits(seeded: Session) -> None:
    result = auth_svc.login(
        seeded, user_id="ops.maker", password=TEST_PASSWORD, totp=None, ip="10.0.0.1"
    )
    assert result.user.id == "ops.maker"
    assert result.must_change_password is True
    claims = auth_svc.decode_token(result.token)
    assert claims.sub == "ops.maker"
    assert claims.role is UserRole.MAKER
    logins = seeded.query(AuditLog).filter(AuditLog.action == "LOGIN").count()
    assert logins == 1


def test_five_failures_lock_the_account_for_fifteen_minutes(seeded: Session) -> None:
    settings = get_settings()
    for _ in range(settings.max_failed_attempts - 1):
        with pytest.raises(NotAuthenticated):
            auth_svc.login(seeded, user_id="ops.maker", password="wrong", totp=None)
    with pytest.raises(NotAuthenticated, match="locked"):
        auth_svc.login(seeded, user_id="ops.maker", password="wrong", totp=None)

    user = seeded.get(User, "ops.maker")
    assert user is not None and user.locked_until is not None
    assert user.locked_until - utcnow() <= timedelta(minutes=settings.lockout_minutes)

    # even the right password is refused while the account is locked
    with pytest.raises(NotAuthenticated, match="locked"):
        auth_svc.login(seeded, user_id="ops.maker", password=TEST_PASSWORD, totp=None)

    assert seeded.query(AuditLog).filter(AuditLog.action == "ACCOUNT_LOCKED").count() == 1
    assert seeded.query(AuditLog).filter(AuditLog.action == "LOGIN_FAILED").count() == 4


def test_the_service_account_cannot_sign_in(seeded: Session) -> None:
    with pytest.raises(NotAuthenticated, match="service account"):
        auth_svc.login(seeded, user_id=SYSTEM_USER, password="anything", totp=None)


def test_mfa_is_required_for_signatories_once_enrolled(seeded: Session) -> None:
    assert auth_svc.mfa_required(UserRole.SIGNATORY)
    assert auth_svc.mfa_required(UserRole.FINANCE)
    assert auth_svc.mfa_required(UserRole.ADMIN)
    assert not auth_svc.mfa_required(UserRole.MAKER)

    user = seeded.get(User, "sig.one")
    assert user is not None
    secret, uri = auth_svc.start_mfa_enrolment(seeded, user, actor_id=user.id)
    assert "otpauth://" in uri
    assert user.totp_secret is not None and secret not in user.totp_secret

    auth_svc.complete_mfa_enrolment(seeded, user, pyotp.TOTP(secret).now(), actor_id=user.id)
    assert user.totp_enrolled

    # "we need your one-time code" carries its own code, so the sign-in screen can
    # show the authenticator step instead of an error -- while still being a 401 that
    # says nothing about whether the password was right.
    with pytest.raises(MfaRequired, match="authenticator code is required") as missing:
        auth_svc.login(seeded, user_id="sig.one", password=TEST_PASSWORD, totp=None)
    assert missing.value.code == "MFA_REQUIRED"
    assert missing.value.status == 401
    assert isinstance(missing.value, NotAuthenticated)

    # A wrong code stays indistinguishable from a wrong password.
    with pytest.raises(NotAuthenticated, match="not valid") as wrong:
        auth_svc.login(seeded, user_id="sig.one", password=TEST_PASSWORD, totp="000000")
    assert wrong.value.code == "NOT_AUTHENTICATED"

    result = auth_svc.login(
        seeded, user_id="sig.one", password=TEST_PASSWORD, totp=pyotp.TOTP(secret).now()
    )
    assert result.mfa_enrolment_required is False


def test_changing_the_password_revokes_existing_tokens(seeded: Session) -> None:
    result = auth_svc.login(seeded, user_id="ops.maker", password=TEST_PASSWORD, totp=None)
    token = result.token
    assert auth_svc.user_from_token(seeded, token).id == "ops.maker"

    auth_svc.change_password(
        seeded, result.user, current=TEST_PASSWORD, new="Brand-New-Password-2026!"
    )
    with pytest.raises(NotAuthenticated, match="revoked"):
        auth_svc.user_from_token(seeded, token)

    fresh = auth_svc.login(
        seeded, user_id="ops.maker", password="Brand-New-Password-2026!", totp=None
    )
    assert fresh.must_change_password is False


def test_a_deactivated_user_cannot_use_an_existing_token(seeded: Session) -> None:
    result = auth_svc.login(seeded, user_id="ops.maker", password=TEST_PASSWORD, totp=None)
    result.user.active = False
    seeded.flush()
    with pytest.raises(NotAuthenticated, match="not active"):
        auth_svc.user_from_token(seeded, result.token)


def test_unknown_user_is_audited_without_revealing_anything(seeded: Session) -> None:
    with pytest.raises(NotAuthenticated, match="not recognised"):
        auth_svc.login(seeded, user_id="nobody", password="whatever", totp=None)
    row = (
        seeded.query(AuditLog)
        .filter(AuditLog.action == "LOGIN_FAILED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None and row.detail["reason"] == "unknown user"


def test_per_client_access_hides_other_clients(seeded: Session) -> None:
    from app.errors import NotFound
    from app.models import UserClientAccess

    user = seeded.get(User, "ops.maker")
    assert user is not None
    assert auth_svc.accessible_clients(seeded, user) is None

    seeded.add(UserClientAccess(user_id=user.id, client_id="RAYAN", created_by="test"))
    seeded.flush()
    assert auth_svc.accessible_clients(seeded, user) == ["RAYAN"]
    auth_svc.assert_client_access(seeded, user, "RAYAN")
    with pytest.raises(NotFound):
        auth_svc.assert_client_access(seeded, user, "TAAJ")

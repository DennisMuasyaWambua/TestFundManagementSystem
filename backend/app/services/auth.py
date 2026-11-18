"""Authentication: passwords, lockout, TOTP MFA and short-lived access tokens.

The token layer is deliberately thin: an access token carries only ``sub``, ``role``
and ``ver``.  Replacing passwords with OIDC later means swapping the credential check
in :func:`login` for an identity-provider assertion and leaving everything else alone.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import BusinessRule, Conflict, MfaRequired, NotAuthenticated, NotFound
from app.models import User, UserClientAccess, UserRole, utcnow
from app.services import audit

_hasher = PasswordHasher()
ALGORITHM = "HS256"


# --- Passwords ---------------------------------------------------------------


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(hashed: str, raw: str) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, raw)
    except VerifyMismatchError:
        return False
    except Exception:  # malformed hash in the database
        return False


def check_password_policy(raw: str) -> None:
    """At least 12 characters with upper, lower, digit and symbol."""
    settings = get_settings()
    problems: list[str] = []
    if len(raw) < settings.password_min_length:
        problems.append(f"at least {settings.password_min_length} characters")
    if not re.search(r"[A-Z]", raw):
        problems.append("an upper case letter")
    if not re.search(r"[a-z]", raw):
        problems.append("a lower case letter")
    if not re.search(r"[0-9]", raw):
        problems.append("a digit")
    if not re.search(r"[^A-Za-z0-9]", raw):
        problems.append("a symbol")
    if problems:
        raise BusinessRule("the password needs " + ", ".join(problems), requirements=problems)


def temporary_password() -> str:
    """A compliant password for a new or reset account, shown once."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    body = "".join(secrets.choice(alphabet) for _ in range(14))
    return f"{body}!7Aa"


# --- TOTP secrets, encrypted at rest -----------------------------------------


def _fernet() -> Fernet:
    key = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - key rotation accident
        raise BusinessRule("the stored MFA secret cannot be read") from exc


def mfa_required(role: UserRole) -> bool:
    return str(role) in get_settings().mfa_required_roles


def start_mfa_enrolment(db: Session, user: User, *, actor_id: str) -> tuple[str, str]:
    """Generate a TOTP secret.  It is shown once, then only ever stored encrypted."""
    secret = pyotp.random_base32()
    user.totp_secret = encrypt_secret(secret)
    user.totp_enrolled = False
    user.updated_by = actor_id
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name=get_settings().mfa_issuer
    )
    audit.record(db, user_id=actor_id, action="MFA_ENROL_START", entity="user", entity_id=user.id)
    return secret, uri


def verify_totp(user: User, code: str) -> bool:
    if not user.totp_secret:
        return False
    totp = pyotp.TOTP(decrypt_secret(user.totp_secret))
    return bool(totp.verify(code, valid_window=1))


def complete_mfa_enrolment(db: Session, user: User, code: str, *, actor_id: str) -> None:
    if not verify_totp(user, code):
        raise NotAuthenticated("that authenticator code is not valid")
    user.totp_enrolled = True
    user.updated_by = actor_id
    audit.record(
        db, user_id=actor_id, action="MFA_ENROL_COMPLETE", entity="user", entity_id=user.id
    )


# --- Tokens ------------------------------------------------------------------


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    role: UserRole
    ver: int


def issue_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user.id,
        "role": str(user.role),
        "ver": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, expires_in


def decode_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise NotAuthenticated("your session has expired; please sign in again") from exc
    except jwt.PyJWTError as exc:
        raise NotAuthenticated("that access token is not valid") from exc
    return TokenClaims(sub=payload["sub"], role=UserRole(payload["role"]), ver=int(payload["ver"]))


def user_from_token(db: Session, token: str) -> User:
    claims = decode_token(token)
    user = db.get(User, claims.sub)
    if user is None or not user.active:
        raise NotAuthenticated("this account is not active")
    if user.token_version != claims.ver:
        raise NotAuthenticated("your session was revoked; please sign in again")
    return user


def revoke_tokens(user: User) -> None:
    user.token_version += 1


# --- Login -------------------------------------------------------------------


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires_in: int
    user: User
    must_change_password: bool
    mfa_enrolment_required: bool


def login(
    db: Session, *, user_id: str, password: str, totp: str | None, ip: str | None = None
) -> LoginResult:
    settings = get_settings()
    user = (
        db.get(User, user_id)
        or db.execute(select(User).where(User.email == user_id.lower())).scalar_one_or_none()
    )

    if user is None:
        audit.record(
            db,
            user_id=user_id[:32],
            action="LOGIN_FAILED",
            entity="user",
            entity_id=user_id[:64],
            detail={"reason": "unknown user"},
            ip=ip,
        )
        raise NotAuthenticated("those sign-in details are not recognised")

    if not user.can_login:
        audit.record(
            db,
            user_id=user.id,
            action="LOGIN_FAILED",
            entity="user",
            entity_id=user.id,
            detail={"reason": "service account"},
            ip=ip,
        )
        raise NotAuthenticated("this is a service account and cannot sign in")

    if not user.active:
        audit.record(
            db,
            user_id=user.id,
            action="LOGIN_FAILED",
            entity="user",
            entity_id=user.id,
            detail={"reason": "inactive"},
            ip=ip,
        )
        raise NotAuthenticated("this account is not active")

    now = utcnow()
    if user.locked_until is not None and user.locked_until > now:
        audit.record(
            db,
            user_id=user.id,
            action="LOGIN_BLOCKED",
            entity="user",
            entity_id=user.id,
            detail={"locked_until": user.locked_until.isoformat()},
            ip=ip,
        )
        raise NotAuthenticated(
            f"this account is locked until {user.locked_until.strftime('%H:%M')} UTC "
            f"after {settings.max_failed_attempts} failed attempts"
        )

    if not verify_password(user.password_hash, password):
        user.failed_attempts += 1
        detail: dict[str, Any] = {"attempt": user.failed_attempts, "reason": "bad password"}
        if user.failed_attempts >= settings.max_failed_attempts:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_attempts = 0
            detail["locked_until"] = user.locked_until.isoformat()
            audit.record(
                db,
                user_id=user.id,
                action="ACCOUNT_LOCKED",
                entity="user",
                entity_id=user.id,
                detail=detail,
                ip=ip,
            )
            raise NotAuthenticated(
                f"too many failed attempts; this account is locked for "
                f"{settings.lockout_minutes} minutes"
            )
        audit.record(
            db,
            user_id=user.id,
            action="LOGIN_FAILED",
            entity="user",
            entity_id=user.id,
            detail=detail,
            ip=ip,
        )
        raise NotAuthenticated("those sign-in details are not recognised")

    needs_mfa = mfa_required(user.role)
    if needs_mfa and user.totp_enrolled:
        if not totp:
            raise MfaRequired("an authenticator code is required for this role")
        if not verify_totp(user, totp):
            user.failed_attempts += 1
            audit.record(
                db,
                user_id=user.id,
                action="LOGIN_FAILED",
                entity="user",
                entity_id=user.id,
                detail={"reason": "bad totp"},
                ip=ip,
            )
            raise NotAuthenticated("that authenticator code is not valid")

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = now
    token, expires_in = issue_token(user)
    audit.record(
        db,
        user_id=user.id,
        action="LOGIN",
        entity="user",
        entity_id=user.id,
        detail={"role": str(user.role), "mfa": needs_mfa and user.totp_enrolled},
        ip=ip,
    )
    return LoginResult(
        token=token,
        expires_in=expires_in,
        user=user,
        must_change_password=user.must_change_password,
        mfa_enrolment_required=needs_mfa and not user.totp_enrolled,
    )


def change_password(
    db: Session, user: User, *, current: str, new: str, ip: str | None = None
) -> None:
    if not verify_password(user.password_hash, current):
        raise NotAuthenticated("the current password is not correct")
    if current == new:
        raise Conflict("the new password must be different from the current one")
    check_password_policy(new)
    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.updated_by = user.id
    revoke_tokens(user)
    audit.record(
        db, user_id=user.id, action="PASSWORD_CHANGED", entity="user", entity_id=user.id, ip=ip
    )


# --- Per-client access (CoB reg 15) ------------------------------------------


def accessible_clients(db: Session, user: User) -> list[str] | None:
    """The clients this user may see, or None for unrestricted access."""
    rows = (
        db.execute(select(UserClientAccess.client_id).where(UserClientAccess.user_id == user.id))
        .scalars()
        .all()
    )
    return list(rows) or None


def assert_client_access(db: Session, user: User, client_id: str) -> None:
    allowed = accessible_clients(db, user)
    if allowed is not None and client_id not in allowed:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)

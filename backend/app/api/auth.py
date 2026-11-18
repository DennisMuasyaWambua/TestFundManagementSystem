"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ClientIp, CurrentUser, DbSession
from app.errors import BusinessRule
from app.models import User
from app.schemas.common import Ok
from app.schemas.models import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MfaEnrolResponse,
    MfaVerifyRequest,
)
from app.services import auth as auth_svc
from app.services.permissions import permissions_for

router = APIRouter(tags=["auth"])


def me_payload(db: DbSession, user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        name=user.name,
        title=user.title,
        email=user.email,
        role=user.role,
        permissions=permissions_for(user.role),
        client_access=auth_svc.accessible_clients(db, user),
        mfa_enrolled=user.totp_enrolled,
        must_change_password=user.must_change_password,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, db: DbSession, ip: ClientIp) -> LoginResponse:
    result = auth_svc.login(
        db, user_id=body.username, password=body.password, totp=body.totp, ip=ip
    )
    return LoginResponse(
        access_token=result.token,
        expires_in=result.expires_in,
        must_change_password=result.must_change_password,
        mfa_enrolment_required=result.mfa_enrolment_required,
        user=me_payload(db, result.user),
    )


@router.post("/auth/logout", response_model=Ok)
def logout(db: DbSession, user: CurrentUser, ip: ClientIp) -> Ok:
    """Revoke every token issued to this user, including this one."""
    auth_svc.revoke_tokens(user)
    from app.services import audit

    audit.record(db, user_id=user.id, action="LOGOUT", entity="user", entity_id=user.id, ip=ip)
    return Ok(message="signed out")


@router.post("/auth/change-password", response_model=Ok)
def change_password(
    body: ChangePasswordRequest, db: DbSession, user: CurrentUser, ip: ClientIp
) -> Ok:
    auth_svc.change_password(db, user, current=body.current_password, new=body.new_password, ip=ip)
    return Ok(message="password changed; please sign in again")


@router.post("/auth/mfa/enroll", response_model=MfaEnrolResponse)
def enrol_mfa(db: DbSession, user: CurrentUser) -> MfaEnrolResponse:
    """Start MFA enrolment.  The secret is shown exactly once."""
    if user.totp_enrolled:
        raise BusinessRule("this account is already enrolled for MFA")
    secret, uri = auth_svc.start_mfa_enrolment(db, user, actor_id=user.id)
    return MfaEnrolResponse(secret=secret, provisioning_uri=uri)


@router.post("/auth/mfa/verify", response_model=Ok)
def verify_mfa(body: MfaVerifyRequest, db: DbSession, user: CurrentUser) -> Ok:
    auth_svc.complete_mfa_enrolment(db, user, body.code, actor_id=user.id)
    return Ok(message="MFA enrolment complete")


@router.get("/me", response_model=MeResponse)
def me(db: DbSession, user: CurrentUser) -> MeResponse:
    return me_payload(db, user)

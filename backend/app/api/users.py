"""User administration.  ADMIN only, and ADMIN has no money powers."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, needs
from app.errors import Conflict, NotFound
from app.models import User, UserClientAccess
from app.schemas.common import Ok
from app.schemas.models import (
    CreateUserRequest,
    CreateUserResponse,
    UpdateUserRequest,
    UserRow,
)
from app.services import audit
from app.services import auth as auth_svc
from app.services.permissions import Permission

router = APIRouter(tags=["users"])
ADMIN = needs(Permission.USERS_MANAGE)


def _row(db: Session, user: User) -> UserRow:
    access = (
        db.execute(select(UserClientAccess.client_id).where(UserClientAccess.user_id == user.id))
        .scalars()
        .all()
    )
    return UserRow(
        id=user.id,
        name=user.name,
        title=user.title,
        email=user.email,
        role=user.role,
        active=user.active,
        mfa_enrolled=user.totp_enrolled,
        must_change_password=user.must_change_password,
        last_login=user.last_login,
        client_access=list(access),
    )


@router.get("/users", response_model=list[UserRow])
def list_users(db: DbSession, _: User = ADMIN) -> list[UserRow]:
    rows = db.execute(select(User).order_by(User.id)).scalars()
    return [_row(db, user) for user in rows]


@router.post("/users", response_model=CreateUserResponse, status_code=201)
def create_user(body: CreateUserRequest, db: DbSession, actor: User = ADMIN) -> CreateUserResponse:
    if db.get(User, body.id) is not None:
        raise Conflict(f"user {body.id} already exists", id=body.id)
    temporary = auth_svc.temporary_password()
    user = User(
        id=body.id,
        name=body.name,
        title=body.title,
        email=body.email.lower(),
        role=body.role,
        active=True,
        can_login=True,
        password_hash=auth_svc.hash_password(temporary),
        must_change_password=True,
        created_by=actor.id,
    )
    db.add(user)
    db.flush()
    for client_id in body.client_access:
        db.add(UserClientAccess(user_id=user.id, client_id=client_id, created_by=actor.id))
    db.flush()
    audit.record(
        db,
        user_id=actor.id,
        action="USER_CREATED",
        entity="user",
        entity_id=user.id,
        detail={"role": str(body.role), "client_access": body.client_access},
    )
    return CreateUserResponse(user=_row(db, user), temporary_password=temporary)


@router.patch("/users/{user_id}", response_model=UserRow)
def update_user(
    user_id: str, body: UpdateUserRequest, db: DbSession, actor: User = ADMIN
) -> UserRow:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(f"unknown user {user_id}", id=user_id)
    before = {"name": user.name, "role": str(user.role), "email": user.email}
    if body.name is not None:
        user.name = body.name
    if body.title is not None:
        user.title = body.title
    if body.email is not None:
        user.email = body.email.lower()
    if body.role is not None and body.role != user.role:
        user.role = body.role
        auth_svc.revoke_tokens(user)
    if body.client_access is not None:
        for row in db.execute(
            select(UserClientAccess).where(UserClientAccess.user_id == user_id)
        ).scalars():
            db.delete(row)
        db.flush()
        for client_id in body.client_access:
            db.add(UserClientAccess(user_id=user_id, client_id=client_id, created_by=actor.id))
    user.updated_by = actor.id
    db.flush()
    audit.record(
        db,
        user_id=actor.id,
        action="USER_UPDATED",
        entity="user",
        entity_id=user_id,
        detail={"before": before, "after": {"name": user.name, "role": str(user.role)}},
    )
    return _row(db, user)


@router.post("/users/{user_id}/disable", response_model=UserRow)
def disable_user(user_id: str, db: DbSession, actor: User = ADMIN) -> UserRow:
    """Soft-deactivate: business records are kept for at least seven years."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(f"unknown user {user_id}", id=user_id)
    user.active = False
    user.updated_by = actor.id
    auth_svc.revoke_tokens(user)
    db.flush()
    audit.record(db, user_id=actor.id, action="USER_DISABLED", entity="user", entity_id=user_id)
    return _row(db, user)


@router.post("/users/{user_id}/enable", response_model=UserRow)
def enable_user(user_id: str, db: DbSession, actor: User = ADMIN) -> UserRow:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(f"unknown user {user_id}", id=user_id)
    user.active = True
    user.updated_by = actor.id
    db.flush()
    audit.record(db, user_id=actor.id, action="USER_ENABLED", entity="user", entity_id=user_id)
    return _row(db, user)


@router.post("/users/{user_id}/reset-password", response_model=CreateUserResponse)
def reset_password(user_id: str, db: DbSession, actor: User = ADMIN) -> CreateUserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(f"unknown user {user_id}", id=user_id)
    temporary = auth_svc.temporary_password()
    user.password_hash = auth_svc.hash_password(temporary)
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    user.updated_by = actor.id
    auth_svc.revoke_tokens(user)
    db.flush()
    audit.record(
        db, user_id=actor.id, action="USER_PASSWORD_RESET", entity="user", entity_id=user_id
    )
    return CreateUserResponse(user=_row(db, user), temporary_password=temporary)


@router.post("/users/{user_id}/reset-mfa", response_model=Ok)
def reset_mfa(user_id: str, db: DbSession, actor: User = ADMIN) -> Ok:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(f"unknown user {user_id}", id=user_id)
    user.totp_secret = None
    user.totp_enrolled = False
    user.updated_by = actor.id
    auth_svc.revoke_tokens(user)
    db.flush()
    audit.record(db, user_id=actor.id, action="USER_MFA_RESET", entity="user", entity_id=user_id)
    return Ok(message="MFA reset; the user must enrol again at next sign-in")

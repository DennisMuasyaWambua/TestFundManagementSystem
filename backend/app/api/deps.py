"""FastAPI dependencies: the session, the current user and permission checks."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.db import db_session
from app.errors import NotAuthenticated
from app.models import User
from app.services import auth
from app.services.permissions import Permission, require


def get_db() -> Iterator[Session]:
    yield from db_session()


DbSession = Annotated[Session, Depends(get_db)]


def current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise NotAuthenticated("an access token is required")
    return auth.user_from_token(db, authorization.split(" ", 1)[1].strip())


CurrentUser = Annotated[User, Depends(current_user)]


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


ClientIp = Annotated[str | None, Depends(client_ip)]


def needs(permission: Permission) -> Any:
    """Dependency factory: this endpoint needs *permission*.

    The permission is stamped onto the generated callable so that
    ``tests/test_permissions_matrix.py`` can walk the routing table and generate the
    401/403 contract test directly from the permission table.  The two can therefore
    never drift apart.
    """

    def _check(user: CurrentUser) -> User:
        require(user, permission)
        return user

    _check.fms_permission = permission  # type: ignore[attr-defined]
    return Depends(_check)


def permission_of(dependant: object) -> Permission | None:
    """The permission a solved dependant enforces, if any."""
    call = getattr(dependant, "call", None)
    found = getattr(call, "fms_permission", None)
    if isinstance(found, Permission):
        return found
    for sub in getattr(dependant, "dependencies", ()):
        nested = permission_of(sub)
        if nested is not None:
            return nested
    return None


def guard_client(db: Session, user: User, client_id: str) -> None:
    auth.assert_client_access(db, user, client_id)

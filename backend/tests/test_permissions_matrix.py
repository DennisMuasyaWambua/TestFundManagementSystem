"""The 401/403 contract, generated from the permission table.

Every protected endpoint must return 401 without a token and 403 for a role the
permission table does not allow.  The matrix is walked out of the routing table rather
than typed by hand, so adding an endpoint or changing a permission cannot leave this
test behind.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.api.deps import permission_of
from app.main import create_app
from app.models import User, UserRole
from app.services import auth as auth_svc
from app.services.permissions import PERMISSIONS, Permission, allows
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

SAMPLE_PATHS = {
    "{client_id}": "RAYAN",
    "{batch_id}": "1",
    "{instruction_id}": "1",
    "{valuation_id}": "1",
    "{holding_id}": "FD-R-03",
    "{entry_id}": "1",
    "{journal_id}": "1",
    "{user_id}": "ops.maker",
    "{run_id}": "1",
    "{name}": "holdings",
}


def concrete(path: str) -> str:
    for token, value in SAMPLE_PATHS.items():
        path = path.replace(token, value)
    return path


@pytest.fixture
def client(seeded: Session) -> Iterator[TestClient]:
    seeded.commit()
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def role_tokens(seeded: Session) -> dict[UserRole, str]:
    tokens: dict[UserRole, str] = {}
    for role in UserRole:
        user_id = f"matrix.{role.lower()}"
        user = User(
            id=user_id,
            name=f"Matrix {role}",
            title="Test",
            email=f"{user_id}@example.invalid",
            role=role,
            active=True,
            can_login=True,
            password_hash=auth_svc.hash_password("Matrix-Test-2026!"),
            must_change_password=False,
            created_by="test",
        )
        seeded.add(user)
        seeded.flush()
        tokens[role], _ = auth_svc.issue_token(user)
    seeded.commit()
    return tokens


def walk(routes: object, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Every APIRoute in the app, including those reached through include_router."""
    for route in routes:  # type: ignore[attr-defined]
        if isinstance(route, APIRoute):
            yield prefix, route
            continue
        nested = getattr(route, "original_router", None)
        if nested is not None:
            context = getattr(route, "include_context", None)
            yield from walk(nested.routes, prefix + getattr(context, "prefix", ""))


def protected_routes() -> list[tuple[str, str, Permission]]:
    rows: list[tuple[str, str, Permission]] = []
    for prefix, route in walk(create_app().routes):
        permission = permission_of(route.dependant)
        if permission is None:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append((method, prefix + route.path, permission))
    return rows


def test_every_permission_is_used_by_at_least_one_endpoint() -> None:
    used = {permission for _, _, permission in protected_routes()}
    missing = set(PERMISSIONS) - used
    assert not missing, f"permissions with no endpoint: {sorted(str(m) for m in missing)}"


def test_protected_endpoints_reject_anonymous_callers(client: TestClient) -> None:
    for method, path, _permission in protected_routes():
        response = client.request(method, concrete(path), json={})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_protected_endpoints_reject_the_wrong_role(
    client: TestClient, role_tokens: dict[UserRole, str]
) -> None:
    checked = 0
    for method, path, permission in protected_routes():
        for role, token in role_tokens.items():
            response = client.request(
                method,
                concrete(path),
                json={},
                headers={"authorization": f"Bearer {token}"},
            )
            if allows(role, permission):
                assert response.status_code != 403, (
                    f"{role} should be allowed to {method} {path} but got 403"
                )
            else:
                assert response.status_code == 403, (
                    f"{role} must not {method} {path} ({permission}) but got {response.status_code}"
                )
                assert response.json()["error"]["code"] == "PERMISSION_DENIED"
            checked += 1
    assert checked > 100, "the generated matrix looks suspiciously small"

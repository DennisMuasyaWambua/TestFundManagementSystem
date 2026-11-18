"""End-to-end flows through the HTTP layer.

These exercise the same paths the frontend uses: sign in, load the Rayan opening
balance batch, approve it, raise and settle an instruction, run the month-end close
and read the statement.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TEST_PASSWORD

SEED = Path(__file__).resolve().parents[1] / "seed" / "opening_balances"
CUTOVER = "2026-01-31"


@pytest.fixture
def client(seeded: Session) -> Iterator[TestClient]:
    seeded.commit()
    with TestClient(create_app()) as test_client:
        yield test_client


def sign_in(client: TestClient, user_id: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": user_id, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"authorization": f"Bearer {response.json()['access_token']}"}


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_login_returns_the_permission_set(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "fin.head", "password": TEST_PASSWORD}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["must_change_password"] is True
    assert body["mfa_enrolment_required"] is True
    assert "LEDGER_OPERATIONS" in body["user"]["permissions"]
    assert "INSTRUCTION_APPROVE" not in body["user"]["permissions"]


def test_bad_credentials_use_the_standard_error_shape(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"username": "fin.head", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_money_must_be_sent_as_a_string(client: TestClient) -> None:
    headers = sign_in(client, "ops.maker")
    response = client.post(
        "/api/v1/contributions",
        headers=headers,
        json={
            "client_id": "RAYAN",
            "custody_account_id": "CR0012A",
            "amount": 1000.5,
            "value_date": "2026-02-02",
            "advice_ref": "CR-1",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_templates_are_downloadable(client: TestClient) -> None:
    headers = sign_in(client, "fin.officer")
    response = client.get("/api/v1/opening-balances/templates/holdings.csv", headers=headers)
    assert response.status_code == 200
    assert response.text.startswith("holding_id,asset_class")


def upload(client: TestClient, headers: dict[str, str], batch_id: int, kind: str) -> None:
    name = {"holdings": "holdings", "lines": "lines"}.get(kind, kind)
    content = (SEED / "rayan" / f"{name}.csv").read_bytes()
    response = client.post(
        f"/api/v1/opening-balances/{batch_id}/files",
        headers=headers,
        data={"kind": kind},
        files={"upload": (f"{name}.csv", io.BytesIO(content), "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_rayan_migration_end_to_end(client: TestClient) -> None:
    finance = sign_in(client, "fin.officer")

    created = client.post(
        "/api/v1/opening-balances",
        headers=finance,
        json={
            "client_id": "RAYAN",
            "cutover_date": CUTOVER,
            "profit_treatment": "CLIENT_PROFIT_ONLY",
            "pro_rata_accrual_split": True,
        },
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]

    for kind in ("holdings", "lines", "custodian_balances", "custodian_positions"):
        upload(client, finance, batch_id, kind)

    validated = client.post(f"/api/v1/opening-balances/{batch_id}/validate", headers=finance).json()
    assert validated["ok"] is True, validated["errors"]
    assert validated["totals"]["debits"] == "5619061.17"
    assert validated["totals"]["section_a"] == "5490667.23"
    assert any(w["code"] == "PRO_RATA_ACCRUAL_PLACEHOLDER" for w in validated["warnings"])

    detail = client.get(f"/api/v1/opening-balances/{batch_id}", headers=finance).json()
    assert detail["preview"]["total_debit"] == "5619061.17"
    assert detail["preview"]["balanced"] is True
    assert detail["preview"]["reconciles"] is True

    assert (
        client.post(
            f"/api/v1/opening-balances/{batch_id}/acknowledge-warnings",
            headers=finance,
            json={"note": "Per-deposit accrued profit pending from Absa; placeholder accepted."},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/opening-balances/{batch_id}/submit", headers=finance).status_code
        == 200
    )

    # the preparer cannot approve their own batch
    refused = client.post(f"/api/v1/opening-balances/{batch_id}/approve", headers=finance)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "MAKER_CHECKER_BREACH"

    approver = sign_in(client, "fin.head")
    posted = client.post(f"/api/v1/opening-balances/{batch_id}/approve", headers=approver)
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["holdings_created"] == 7
    assert body["reconciliation_breaks"] == 0
    assert body["locked_through"] == CUTOVER

    statement = client.get(
        f"/api/v1/clients/RAYAN/statement?from={CUTOVER}&to={CUTOVER}", headers=approver
    ).json()
    assert statement["your_account"]["your_balance"] == "5490667.23"
    assert statement["where_held"]["net_holdings"] == "5490667.23"
    assert statement["reconciles"] is True

    pdf = client.get(
        f"/api/v1/clients/RAYAN/statement.pdf?from={CUTOVER}&to={CUTOVER}", headers=approver
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.headers["x-statement-sha256"]) == 64

    dashboard = client.get("/api/v1/dashboard?as_of=2026-01-31", headers=approver).json()
    rayan = next(row for row in dashboard["clients"] if row["client_id"] == "RAYAN")
    assert rayan["net_asset_value"] == "5490667.23"
    assert rayan["reconciles"] is True


def test_back_dated_posting_is_refused_after_the_lock(client: TestClient) -> None:
    finance = sign_in(client, "fin.officer")
    created = client.post(
        "/api/v1/opening-balances",
        headers=finance,
        json={"client_id": "TAAJ", "cutover_date": CUTOVER},
    )
    batch_id = created.json()["id"]
    for kind in ("holdings", "lines", "custodian_balances", "custodian_positions"):
        content = (SEED / "taaj" / f"{kind}.csv").read_bytes()
        client.post(
            f"/api/v1/opening-balances/{batch_id}/files",
            headers=finance,
            data={"kind": kind},
            files={"upload": (f"{kind}.csv", io.BytesIO(content), "text/csv")},
        )
    client.post(f"/api/v1/opening-balances/{batch_id}/validate", headers=finance)
    client.post(
        f"/api/v1/opening-balances/{batch_id}/acknowledge-warnings",
        headers=finance,
        json={"note": "Suspense under review; Wakala breakdown awaited from Bank of Africa."},
    )
    client.post(f"/api/v1/opening-balances/{batch_id}/submit", headers=finance)
    approver = sign_in(client, "fin.head")
    client.post(f"/api/v1/opening-balances/{batch_id}/approve", headers=approver)

    maker = sign_in(client, "ops.maker")
    response = client.post(
        "/api/v1/contributions",
        headers=maker,
        json={
            "client_id": "TAAJ",
            "custody_account_id": "BOA-USD",
            "amount": "1000.00",
            "value_date": "2026-01-15",
            "advice_ref": "BOA-CR-99",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PERIOD_LOCKED"
    assert "closed through 2026-01-31" in response.json()["error"]["message"]

    held = client.get(
        f"/api/v1/clients/TAAJ/statement?from={CUTOVER}&to={CUTOVER}", headers=approver
    ).json()
    assert held["reconciles"] is True
    assert "suspense" in held["held_reason"]


def test_instruction_flow_through_the_api(client: TestClient) -> None:
    maker = sign_in(client, "ops.maker")
    sig_one = sign_in(client, "sig.one")
    sig_two = sign_in(client, "sig.two")
    finance = sign_in(client, "fin.head")

    contribution = client.post(
        "/api/v1/contributions",
        headers=maker,
        json={
            "client_id": "RAYAN",
            "custody_account_id": "CR0012A",
            "amount": "250000.00",
            "value_date": "2026-02-02",
            "advice_ref": "ABSA-CR-500",
        },
    )
    assert contribution.status_code == 201, contribution.text

    payload: dict[str, Any] = {
        "client_id": "RAYAN",
        "custody_account_id": "CR0012A",
        "type": "PLACE_WAKALA",
        "amount": "250000.00",
        "value_date": "2026-02-03",
        "beneficiary": "Absa Bank Kenya PLC",
        "params": {
            "holding_id": "FD-R-08",
            "counterparty": "Absa Bank Kenya PLC",
            "profit_rate": "0.0425",
            "day_basis": 365,
            "maturity_date": "2026-08-14",
            "shariah_cert_ref": "SSB/2026/200",
        },
    }

    checks = client.post("/api/v1/instructions/checks", headers=maker, json=payload).json()
    assert all(check["passed"] for check in checks), checks

    created = client.post("/api/v1/instructions", headers=maker, json=payload)
    assert created.status_code == 201, created.text
    instruction_id = created.json()["id"]
    assert created.json()["reference"] == "INS/2026/0001"

    # the maker cannot approve
    assert (
        client.post(f"/api/v1/instructions/{instruction_id}/approve", headers=maker).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/instructions/{instruction_id}/approve", headers=sig_one).status_code
        == 200
    )
    second = client.post(f"/api/v1/instructions/{instruction_id}/approve", headers=sig_two)
    assert second.status_code == 200
    assert second.json()["status"] == "APPROVED"
    letter_hash = second.json()["letter_pdf_sha256"]

    letter = client.get(f"/api/v1/instructions/{instruction_id}/letter.pdf", headers=maker)
    assert letter.status_code == 200
    assert letter.headers["x-letter-sha256"] == letter_hash

    sent = client.post(
        f"/api/v1/instructions/{instruction_id}/sent",
        headers=maker,
        files={"signed_copy": ("signed.pdf", io.BytesIO(letter.content), "application/pdf")},
    )
    assert sent.status_code == 200
    assert sent.json()["status"] == "SENT"

    mismatch = client.post(
        f"/api/v1/instructions/{instruction_id}/settle",
        headers=finance,
        json={
            "confirmation_ref": "ABSA-CONF-1",
            "settled_on": "2026-02-03",
            "amount": "249999.00",
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "BUSINESS_RULE"

    settled = client.post(
        f"/api/v1/instructions/{instruction_id}/settle",
        headers=finance,
        json={
            "confirmation_ref": "ABSA-CONF-1",
            "settled_on": "2026-02-03",
            "amount": "250000.00",
        },
    )
    assert settled.status_code == 200
    assert settled.json()["status"] == "SETTLED"

    holding = client.get("/api/v1/holdings/FD-R-08", headers=maker).json()
    assert holding["holding"]["status"] == "ACTIVE"
    assert holding["balances"]["outstanding"] == "250000.00"


def test_month_end_close_locks_the_period(client: TestClient) -> None:
    finance = sign_in(client, "fin.head")
    compliance = sign_in(client, "compliance")

    client.post(
        "/api/v1/contributions",
        headers=sign_in(client, "ops.maker"),
        json={
            "client_id": "RAYAN",
            "custody_account_id": "CR0012A",
            "amount": "1000.00",
            "value_date": "2026-02-02",
            "advice_ref": "ABSA-CR-1",
        },
    )
    period_end = "2026-02-28"
    client.post(
        "/api/v1/custodian-balances",
        headers=compliance,
        json={
            "custody_account_id": "CR0012A",
            "as_of": period_end,
            "balance": "1000.00",
            "statement_ref": "ABSA-STMT-02",
        },
    )
    checklist = client.get(
        f"/api/v1/clients/RAYAN/close-checklist?period_end={period_end}", headers=finance
    ).json()
    assert {item["key"] for item in checklist["items"]} >= {
        "period_open",
        "accruals",
        "fx_revaluation",
        "reconciliation",
        "valuations",
    }

    closed = client.post(
        f"/api/v1/clients/RAYAN/close?period_end={period_end}", headers=finance, json={}
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["locked_through"] == period_end

    again = client.post(
        f"/api/v1/clients/RAYAN/close?period_end={period_end}", headers=finance, json={}
    ).json()
    assert again["already_closed"] is True


def test_audit_log_is_visible_to_compliance_only(client: TestClient) -> None:
    compliance = sign_in(client, "compliance")
    maker = sign_in(client, "ops.maker")
    assert client.get("/api/v1/audit-log", headers=maker).status_code == 403
    response = client.get("/api/v1/audit-log?limit=5", headers=compliance)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert {"at", "user_id", "action", "entity"} <= set(body["items"][0])


def test_trial_balance_balances_over_the_api(client: TestClient) -> None:
    headers = sign_in(client, "fin.head")
    response = client.get(
        f"/api/v1/reports/trial-balance?as_of={date(2026, 12, 31).isoformat()}", headers=headers
    ).json()
    assert response["balanced"] is True
    assert response["total_debit"] == response["total_credit"]


def test_get_clients_returns_onboarding_gaps_as_a_list(client: TestClient) -> None:
    """Regression test: ``Client.onboarding_gaps`` is a property, not a plain method.

    ``ClientRow.model_validate(client, from_attributes=True)`` reads it as an
    attribute before any application code runs. A plain method would hand Pydantic
    the bound method object itself and this would 500 on every single call, not just
    this one -- there is no endpoint that lists clients without this.
    """
    maker = sign_in(client, "ops.maker")

    response = client.get("/api/v1/clients", headers=maker)

    assert response.status_code == 200, response.text
    rows = response.json()
    ids = {row["id"] for row in rows}
    assert {"RAYAN", "TAAJ"} <= ids
    for row in rows:
        assert isinstance(row["onboarding_gaps"], list)
        for gap in row["onboarding_gaps"]:
            assert isinstance(gap, str)

    # Both go-live mandates are fully onboarded by the seed: no gaps.
    by_id = {row["id"]: row for row in rows}
    assert by_id["RAYAN"]["onboarding_gaps"] == []
    assert by_id["TAAJ"]["onboarding_gaps"] == []


def test_a_client_missing_its_agreement_shows_the_gap(client: TestClient) -> None:
    finance = sign_in(client, "fin.head")

    created = client.post(
        "/api/v1/clients",
        json={"id": "GAPTEST", "legal_name": "Gap Test Mandate", "base_currency": "USD"},
        headers=finance,
    )
    assert created.status_code in (200, 201), created.text

    rows = client.get("/api/v1/clients", headers=finance).json()
    row = next(r for r in rows if r["id"] == "GAPTEST")

    assert any("agreement" in gap for gap in row["onboarding_gaps"])
    assert any("KYC" in gap for gap in row["onboarding_gaps"])

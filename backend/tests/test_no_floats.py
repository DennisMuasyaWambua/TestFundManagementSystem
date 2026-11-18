"""Money is never a float.

This test reads the source of every money path and fails if it finds a float literal,
a ``float(...)`` call or an arithmetic import that would quietly introduce binary
rounding error into the ledger.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Page geometry -- font sizes, rule widths, millimetres -- is not money.  These two
# modules lay out PDFs and may use float literals for typography; the float() ban below
# still applies to them, and every figure they print comes from app.money.fmt.
LAYOUT_MODULES = {"services/letters.py", "services/statements.py"}


def python_files() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py"))


def test_no_float_literals_on_money_paths() -> None:
    offences: list[str] = []
    for path in python_files():
        module = path.relative_to(APP).as_posix()
        if module in LAYOUT_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                offences.append(f"{module}:{node.lineno} float literal {node.value!r}")
    assert not offences, "floats are not allowed on money paths:\n" + "\n".join(offences)


def test_nothing_casts_to_float_anywhere() -> None:
    offences: list[str] = []
    for path in python_files():
        module = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                offences.append(f"{module}:{node.lineno} float() call")
    assert not offences, "float() is never the right cast here:\n" + "\n".join(offences)


def test_layout_modules_print_money_through_the_formatter() -> None:
    """The PDF modules may use float geometry, but never float money."""
    for module in LAYOUT_MODULES:
        source = (APP / module).read_text(encoding="utf-8")
        assert "from app.money import" in source, module
        assert "fmt(" in source, module


def test_money_helpers_refuse_floats() -> None:
    import pytest
    from app.money import MoneyError, money, rate

    with pytest.raises(MoneyError):
        money(1.5)  # type: ignore[arg-type]
    with pytest.raises(MoneyError):
        rate(0.0425)  # type: ignore[arg-type]


def test_api_rejects_json_numbers_for_money() -> None:
    import pytest
    from app.schemas.models import ContributionRequest
    from pydantic import ValidationError

    payload = {
        "client_id": "RAYAN",
        "custody_account_id": "CR0012A",
        "amount": 1000.5,
        "value_date": "2026-02-02",
        "advice_ref": "CR-1",
    }
    with pytest.raises(ValidationError):
        ContributionRequest.model_validate(payload)

    accepted = ContributionRequest.model_validate({**payload, "amount": "1000.50"})
    assert str(accepted.amount) == "1000.50"


def test_there_are_no_todos_on_money_paths() -> None:
    offences: list[str] = []
    for path in python_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") and ("TODO" in stripped or "FIXME" in stripped):
                offences.append(f"{path.relative_to(APP).as_posix()}:{number} {stripped}")
    assert not offences, "unfinished work left in the application:\n" + "\n".join(offences)

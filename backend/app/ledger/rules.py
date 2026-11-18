"""Posting rules, stored as data.

``seed/posting_rules.csv`` holds one row per journal line: the rule key, the ledger
event it posts, the side, the role and the amount key.  Business code supplies a dict
of amounts and the rule table decides the shape of the entry -- no ``if event ==``
chains anywhere.

Four events have a line set that depends on the data rather than on a fixed template
and are therefore built directly by their service, not from this table:
``OPENING_BALANCE`` (one line per staged row), ``FX_REVALUATION`` (one line per
foreign-currency balance), ``MONTH_END_CLOSE`` (one line per P&L account) and
``REVERSAL`` (the mirror of whatever it reverses).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.errors import BusinessRule
from app.ledger.roles import Role
from app.models import LedgerEvent

RULES_CSV = Path(__file__).resolve().parents[2] / "seed" / "posting_rules.csv"


@dataclass(frozen=True)
class PostingRule:
    rule_key: str
    event: LedgerEvent
    side: str
    role: Role
    amount_key: str
    required: bool

    @property
    def sign(self) -> Decimal:
        """Debit is positive, credit is negative."""
        return Decimal(1) if self.side == "DEBIT" else Decimal(-1)


@lru_cache(maxsize=1)
def _load() -> dict[str, tuple[PostingRule, ...]]:
    grouped: dict[str, list[PostingRule]] = {}
    with RULES_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            side = row["side"].strip()
            if side not in {"DEBIT", "CREDIT"}:
                raise ValueError(f"bad side {side!r} in posting_rules.csv")
            rule = PostingRule(
                rule_key=row["rule_key"].strip(),
                event=LedgerEvent(row["event"].strip()),
                side=side,
                role=Role(row["role"].strip()),
                amount_key=row["amount_key"].strip(),
                required=row["required"].strip() == "1",
            )
            grouped.setdefault(rule.rule_key, []).append(rule)
    return {key: tuple(rules) for key, rules in grouped.items()}


def rules_for(rule_key: str) -> tuple[PostingRule, ...]:
    rules = _load().get(rule_key)
    if not rules:
        raise BusinessRule(f"no posting rule named {rule_key!r}", rule_key=rule_key)
    return rules


def event_for(rule_key: str) -> LedgerEvent:
    return rules_for(rule_key)[0].event


def all_rule_keys() -> tuple[str, ...]:
    return tuple(sorted(_load()))


def required_amount_keys(rule_key: str) -> tuple[str, ...]:
    return tuple(rule.amount_key for rule in rules_for(rule_key) if rule.required)

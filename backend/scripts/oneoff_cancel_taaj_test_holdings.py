"""One-off: cancel the two holdings batch #13 created on TAAJ.

Batch 13 was an experimental opening-balance load with unconfirmed placeholder
accrual figures. Its journal effect was already corrected with a proper reversal
(entry #2, reverses entry #1) -- that part of the ledger is append-only and stays
exactly as it happened, by design.

The two holdings it created (SUK-T-01, FD-T-02) are not in an append-only table,
but there is no "delete/cancel a holding" endpoint yet -- only write-off, which
books a real loss entry. Nothing was actually lost here, so write-off is the
wrong tool. This marks them CANCELLED directly and records why, the same way
any other state change in this app is audited.

Run once, from inside the api container, then delete this file:
    docker compose exec -T api python3 - < scripts/oneoff_cancel_taaj_test_holdings.py
"""

from __future__ import annotations

from app.db import session_scope
from app.models import Holding, HoldingStatus
from app.services import audit

HOLDING_IDS = ["SUK-T-01", "FD-T-02"]
REASON = (
    "Created by opening-balance batch 13 (TAAJ), which was reversed (ledger entry "
    "#2 reverses entry #1) after being loaded with unconfirmed placeholder accrual "
    "figures during a pipeline/learning exercise. No write-off booked: nothing was "
    "lost, the opening entry was corrected, so this holding should not have stayed "
    "active."
)

with session_scope() as db:
    for holding_id in HOLDING_IDS:
        holding = db.get(Holding, holding_id)
        if holding is None:
            print(f"{holding_id}: not found, skipping")
            continue
        if holding.status == HoldingStatus.CANCELLED:
            print(f"{holding_id}: already cancelled")
            continue
        previous_status = str(holding.status)
        holding.status = HoldingStatus.CANCELLED
        audit.record(
            db,
            user_id="fin.head",
            action="HOLDING_CANCELLED",
            entity="holding",
            entity_id=holding_id,
            client_id=holding.client_id,
            detail={"previous_status": previous_status, "reason": REASON},
        )
        print(f"{holding_id}: cancelled ({previous_status} -> CANCELLED)")

# Architecture

## The shape

```
┌──────────┐   HTTPS    ┌─────────────────────┐   HTTPS    ┌──────────────┐
│ Browser  │ ─────────▶ │  Next.js            │ ─────────▶ │ Python API   │
│          │            │  route handlers     │            │ (FastAPI)    │
│ no token │ ◀───────── │  (backend-for-      │ ◀───────── │              │
│ ever     │            │   frontend)         │            │ every rule   │
└──────────┘            └─────────────────────┘            └──────┬───────┘
                          httpOnly cookie                          │
                          holds the token                          ▼
                                                            ┌──────────────┐
                                                            │ PostgreSQL 16│
                                                            │ append-only  │
                                                            │ ledger       │
                                                            └──────────────┘
                                                                   ▲
                                                            ┌──────┴───────┐
                                                            │ Worker       │
                                                            │ (APScheduler)│
                                                            └──────────────┘
```

**Why the browser never talks to the API directly.** The backend token is a bearer
token: anything that can read it can act as that user until it expires. Keeping it in
an httpOnly, `SameSite=Strict`, `Secure` cookie means script on the page cannot read
it — so an injected script, a malicious dependency or a browser extension has nothing
to take. The page's own fetches go to `/api/v1/...` on the same origin, where
`app/api/[...path]/route.ts` attaches the token server-side.

**Why the API is the only authority.** The frontend hides what a role cannot do, but
it never decides. Every request is authorised again by the API, and a 403 is rendered
as a page the user can read. A user who types a URL for a screen their role cannot
use gets the API's refusal, not a blank page. The 401/403 contract is tested from the
permission table itself (`tests/test_permissions_matrix.py`), so the two cannot drift.

---

## Backend layers

Each layer may only call the one below it.

| Layer | Module | Responsibility |
| --- | --- | --- |
| HTTP | `app/api/` | Validate the request, call one service, map an `AppError` to the single error shape. Thin by design — no business logic. |
| Business | `app/services/` | The workflows: onboarding, receipts, instructions, accruals, FX, valuations, reconciliation, closing, opening balances, reports, statements. |
| Ledger | `app/ledger/` | `post()` and its validation, posting rules as data, role resolution, balances, reversal. The only code that writes to the journal. |
| Data | `app/models/`, `app/db.py` | SQLAlchemy models, the `NUMERIC` money types, the append-only DDL. |

A service never writes a journal line itself: it builds `LineDraft`s and calls
`ledger.post()`, which is the single gate every posting passes through.

### `post()` validation, in order

Any failure rejects the whole entry.

1. The client exists and is not closed; at least two lines move a non-zero amount.
2. Each line's currency defaults to the entry's; the FX rate for the entry date is
   looked up (the latest on or before it — **a missing rate is a hard error naming the
   currency and the date**, never a silent 1.0); `base_amount = round(amount × rate)`.
3. A single-currency entry must sum to zero in that currency, with any base-currency
   rounding cent absorbed on the largest line. A multi-currency entry (FX only) must
   balance in base currency, or the difference goes to FX gain or loss when the caller
   allows it.
4. The entry date must be after the client's period lock.
5. Each account exists, is postable and active; an account that needs a sub-ledger
   carries a holding id; firm equity accounts are refused outright for client money.
6. A client-owned account takes only that client's lines, and each holding belongs to
   the entry's client.
7. The entry, its lines and an audit row are written in the same transaction.

### Posting rules as data

Events (`INVESTMENT_PLACED`, `PROFIT_ACCRUED`, `INVESTMENT_MATURED`, …) are rows, not
branches: one row per line, naming the side, the **role** and which amount it takes.
`{INVESTMENT}`, `{INCOME}`, `{FEE_EXPENSE}` and `{FV_ADJUSTMENT}` resolve from the
holding's asset class; `BANK` resolves from the custody account's cash code. Zero-amount
lines are skipped. Adding a chart-of-accounts mapping is a seed change, not a code
change — which is also why account codes appear nowhere in the business logic.

### Where "never a float" is actually enforced

| Place | Mechanism |
| --- | --- |
| PostgreSQL | `NUMERIC(24,2)` amounts, `NUMERIC(24,8)` rates |
| SQLite (dev and tests) | Scaled integers — cents, and rate × 10⁸ — because SQLite coerces `NUMERIC` to a float and `SUM()` would drift |
| Python | `Decimal` throughout; rounding is half-up and happens only at the defined points (the end of an accrual, a conversion, a fee) |
| The API boundary | Money and rates are **strings** in JSON, with a regex on the schema |
| TypeScript | Money is a `string`, formatted by `lib/money.ts`, which contains no arithmetic; ESLint fails the build on `parseFloat` |
| Tests | `tests/test_no_floats.py` greps the money paths for float literals and `float()` |

The one place the frontend combines amounts — a headline total on the dashboard — does
it in `BigInt` cents parsed from the string, and the one place it produces a number
(asset-mix bar widths) produces a CSS width that is never shown as money.

---

## Idempotency

Accruals, rent invoicing, FX revaluation and the close can all be re-run — by the
scheduler after a failure, or by hand — without double-posting:

- **Accruals** compute the cumulative *profit to date* for a holding and post only the
  difference against what is already booked. Running twice posts nothing the second
  time.
- **Rent** is keyed on `RENT-<holding>-<YYYY-MM>`, which is unique.
- **FX revaluation** computes the target base amount for each balance and posts the
  delta.
- **Close** is a no-op once the period is locked.
- **Mutating API calls** accept an `Idempotency-Key` header, and the UI sends a fresh
  one per attempt of a money-moving action.

`tests/test_jobs.py` asserts the re-run behaviour, and that one client's bad data (a
closed period, a missing rate) cannot stop the others from being accrued.

---

## Instruction lifecycle

```
PENDING_APPROVAL
   │  two SIGNATORY approvals, neither the maker
   ▼
APPROVED            ← the PDF letter is generated, its SHA-256 stored
   │  the wet-signed scan is uploaded, its SHA-256 stored
   ▼
SENT
   │  the custodian's confirmation reference, settled date and amount
   │  (the amount must equal what was instructed)
   ▼
SETTLED             ← and only now is anything posted to the ledger

PENDING_APPROVAL / APPROVED ──▶ REJECTED or CANCELLED, with a reason
```

The checks at creation: KYC approved, agreement and custody appointment on file,
amount above zero, **cash available** (ledger balance less every instruction already
pending, approved or sent on that account), deal terms and a Shariah approval
reference for investments, a payout within the client's profit or capital, and the
client's own written request reference for a payout.

References are `INS/<year>/<4-digit sequence>`, gap-free per year via a sequence table
with a row lock.

The letter is deterministic — ReportLab with `invariant=1` and no timestamp — so the
stored hash always matches a regenerated copy. `tests/test_instructions.py` asserts
that the same instruction produces identical bytes.

---

## Frontend

**Server Components fetch; Client Components interact.** A read-only page is a Server
Component calling `lib/api/server.ts`, so no data fetching happens in the browser and
no API shape leaks into client bundles. Anything that mutates is a Client Component
calling `lib/api/client.ts`, which goes through the proxy with a CSRF header.

**The CSRF pair.** The session cookie is httpOnly; a second, readable cookie holds a
random token. Mutating requests must echo it in `x-fms-csrf`, which script on another
origin cannot do. The proxy rejects a mismatch with 403 before the request reaches the
API.

**Money in the UI.** Amounts arrive as strings, are rendered by `<Money>` with tabular
figures and right alignment, and negatives are bracketed. Amount inputs are
`type="text"` with `inputMode="decimal"` — never `type="number"`, which would hand
JavaScript a float.

**Accessibility.** No meaning is carried by colour alone: every status pill and every
stepper step spells its state out in text. Tables are real tables with scoped headers,
inputs are labelled, focus is always visible, and interactive targets are at least
44 px. Wide tables scroll inside their own container so the page body never scrolls
sideways.

**Sessions.** A warning appears at 25 minutes idle and the user is signed out at 30,
matching the token's life. A 401 from anywhere redirects to `/login` keeping the
return URL.

---

## Request lifecycle

One request is one database transaction. `db_session()` opens it, the router calls one
service, and the transaction commits when the response is produced or rolls back
entirely on any exception. There is no partial save: an instruction cannot be marked
settled without its journal entry, and a migration batch cannot be posted without its
holdings.

## Scheduled work

`app/jobs/worker.py` runs two schedules in Africa/Nairobi:

- **01:30 daily** — accrue profit, invoice rent and charge fees up to *yesterday*
  (profit for day D is only complete once D has ended).
- **02:30 on the 1st** — revalue foreign-currency balances at the closing rate of the
  month that just ended.

Each job runs in its own transaction per client and records failures in the audit log
rather than raising, because a scheduler that dies on the first error silently stops
accruing for everyone. **The worker never closes a period**: that needs a human who has
cleared the reconciliation, so it stays an act by finance on `/close`.

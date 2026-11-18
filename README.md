# Shariah fund management system

A fund management system for a Kenyan investment bank licensed by the Capital Markets
Authority. It manages **segregated client mandates** invested only in
Shariah-compliant assets — Wakala deposits, Sukuk, private financing and investment
property — held by **custodian banks**.

The bank never moves money itself. It sends the custodian a letter signed by two
authorised signatories, and the movement is booked **only after the custodian
confirms it**.

| Part | Stack | What it owns |
| --- | --- | --- |
| `backend/` | Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL 16 | The double-entry ledger, every business rule, PDF letters, reports, the REST API |
| `frontend/` | Next.js 15 (App Router), TypeScript, Tailwind CSS 4 | Screens for operations, signatories, finance and compliance |
| `docs/` | Markdown | Architecture, the CMA control map, runbooks, open decisions |

---

## Running it

```bash
docker compose up --build
```

That brings up PostgreSQL, Redis, the API, the scheduled worker and the web app, and
runs the migration and the seed on the way. Then:

- the web app is at <http://localhost:3000>
- the API's OpenAPI explorer is at <http://localhost:8000/docs>

The seed prints a temporary password for each starter user. To set a known one for
local work:

```bash
docker compose run --rm api python -m scripts.seed --password 'Local-Dev-Pass-1!'
```

### Starter users

| Username | Role | What they can do |
| --- | --- | --- |
| `ops.maker` | MAKER | Prepare instructions, record receipts |
| `sig.one`, `sig.two` | SIGNATORY | Approve instructions (two needed, neither the preparer) |
| `fin.head`, `fin.officer` | FINANCE | Accruals, FX, month-end close, opening balances, reconciliation |
| `compliance` | COMPLIANCE | KYC, reconciliation, the audit log |
| `admin` | ADMIN | Users only — **no authority over money** |

Multi-factor authentication is mandatory for SIGNATORY, FINANCE and ADMIN. A seeded
user enrols an authenticator on first sign-in at `/settings/profile`.

### Without Docker

```bash
# Backend
cd backend
python -m venv .venv && . .venv/Scripts/activate   # or bin/activate
pip install -e ".[dev]"
export FMS_SECRET_KEY='something-long-and-random'
export FMS_DATABASE_URL='postgresql+psycopg://fms:fms@localhost:5432/fms'
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload

# Frontend, in another shell
cd frontend
npm install
FMS_API_URL=http://localhost:8000/api/v1 npm run dev
```

SQLite works for the backend too (`FMS_DATABASE_URL=sqlite+pysqlite:///var/fms.sqlite`)
and is what the test suite uses; money is stored there as scaled integers so sums stay
exact. PostgreSQL is the production database.

---

## Checks

Every one of these must pass; CI runs all of them (`.github/workflows/ci.yml`).

```bash
# Backend
cd backend
ruff check . && ruff format --check .
mypy --strict app scripts
pytest -q
python scripts/export_openapi.py --check      # the committed OpenAPI document is current

# Frontend
cd frontend
npm run lint
npm run typecheck
npm run test                                  # Vitest
npm run e2e                                   # Playwright, needs the API running
npm run generate:api                          # regenerate types/api.d.ts after an API change
```

CI additionally runs the migration up, down and up again against PostgreSQL 16, and
re-runs the schema and append-only assertions there.

---

## How money works here

Thirteen rules shape every line of the backend. The ones that bite hardest:

1. **Money is never a float.** `Decimal` in Python, `NUMERIC(24,2)` for amounts and
   `NUMERIC(24,8)` for rates in PostgreSQL. In TypeScript money is a **string** that is
   formatted and never calculated — `frontend/lib/money.ts` contains no arithmetic, and
   ESLint fails the build on `parseFloat`.
2. **Double entry.** Every entry has two or more signed lines (debit +, credit −),
   sums to zero in its own currency, and sums to zero in the client's base currency.
3. **The ledger is append-only.** A database trigger rejects `UPDATE` and `DELETE` on
   `journal_entries`, `journal_lines` and `audit_log`. A mistake is corrected by a
   reversal entry plus a new correct one.
4. **Roles, not account codes.** Business code asks for `CLIENT_CAPITAL`; a
   role-mapping table resolves it per client. Account codes live only in seed data.
5. **Segregation is enforced in the ledger.** Every line carries a `client_id`, and a
   client-owned account rejects another client's line.
6. **Nothing leaves custody without an instruction.** Outgoing money is booked only
   when a SENT instruction is confirmed, for exactly the instructed amount.
7. **Maker–checker.** Instructions need two signatories, neither the preparer.
   Valuations, opening balance batches and manual journals each need a second person.
8. **Closed periods are locked.** After a month-end close, nothing can be posted on or
   before the closed date.

Terminology is Shariah-compliant throughout — **profit**, never interest — in the code,
the API field names, the PDF letters and the UI.

### The shape of it

```
Browser ──▶ Next.js route handlers (the BFF) ──▶ Python API ──▶ PostgreSQL
            the token lives here, in an               every business rule
            httpOnly cookie the browser               and the ledger
            cannot read
```

The browser never holds the backend token and never learns the API's address. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Golden numbers

Section 12 of the specification fixes nine scenarios that must come out to the cent.
They are integration tests, not documentation:

| # | Scenario | Test |
| --- | --- | --- |
| G1 | Rayan opening batch: debits = credits = 5,619,061.17; A = B = 5,490,667.23 | `tests/test_golden_migration.py` |
| G2 | Taaj opening batch: 7,614,827.62; suspense 516,745.92; statement held | `tests/test_golden_migration.py` |
| G3 | Wakala 1,000,000 at 4.25%: January 3,609.59; total 26,198.63; bank 1,022,268.84; client profit 19,648.98 | `tests/test_golden_wakala.py` |
| G4 | The same deposit to 31 March: income 10,479.45, fee 1,047.95 | `tests/test_golden_wakala.py` |
| G5 | Private financing part repayment: 5,000.00 on the reduced balance | `tests/test_golden_scenarios.py` |
| G6 | KES deposit through revaluation and a clean close | `tests/test_golden_scenarios.py` |
| G7 | KES→USD conversion off the day's rate: FX loss 1,000.00 | `tests/test_golden_scenarios.py` |
| G8 | Sukuk at a discount, revalued, redeemed at par: net gain 20,000 | `tests/test_golden_scenarios.py` |
| G9 | Property revalued to 2,150,000: adjustment 150,000 | `tests/test_golden_scenarios.py` |

```bash
cd backend && pytest -m golden -q
```

---

## Open decisions

Each of these is **configuration with the documented default**, in
`backend/app/config.py` unless noted. They stay here until the owner confirms them.

| # | Decision | Default in force | Where | Owner |
| --- | --- | --- | --- | --- |
| 1 | Cutover date | Chosen per batch; must be a date before every migrated holding's maturity | `opening_balance_batches.cutover_date` | Finance |
| 2 | Current-year profit at migration | Client profit only — three lines on 2210/2220. `INCLUDE_PL` is built and selectable | `profit_treatment` on the batch | Finance |
| 3 | Per-deposit accrued profit (Rayan total 16,408.80; Taaj breakdown) | **Blocked** unless the pro-rata placeholder is chosen, which raises a warning that must be acknowledged in writing | `pro_rata_accrual_split` on the batch | Finance + custodians |
| 4 | The Taaj gap of 516,745.92 | Carried on suspense 1390; Taaj statements are held until cleared | Posted by the batch | Finance |
| 5 | Taaj receivables 1,400,509.69 classification | `1320` Accounts receivable | `taaj_receivable_account` | Finance |
| 6 | Management fee basis and rate | 10% of income, per client and asset class | `default_management_fee_pct`, `mandate_fees` | Management / mandate terms |
| 7 | Withholding tax rates | At source: entered per receipt. Final: 0% | `default_final_wht_rate`, `clients.final_wht_rate` | Tax adviser |
| 8 | Day basis per counterparty | 365 | `default_day_basis`, `holdings.day_basis` | Finance |
| 9 | New accounts 1231, 1261, 4230, 5350 | Added, flagged `is_proposed` pending finance approval | `seed/chart_of_accounts.csv` | Finance |
| 10 | Sukuk (IFRS 9) and property (IAS 40) measurement | Fair value through profit and loss, via the adjustment accounts | Posting rules | Auditors |
| 11 | Signatories per instruction, value thresholds | 2 for every amount; no thresholds | `required_signatories` | Board |
| 12 | Custodian statement import formats | Manual entry and CSV only; MT940 and API feeds not built | `/custodian-balances`, `/custodian-positions` | Operations |
| 13 | Letterhead, CMA licence number, signatory titles | Clearly marked placeholders | `firm_name`, `firm_address`, `firm_contact`, `cma_licence_number` | Management |
| 14 | Shariah purification of non-compliant income | Not built | — | Shariah adviser |

**No figure, rate or client detail anywhere in this repository was invented.** Everything
is either from the specification or a marked placeholder (`<ADDRESS PLACEHOLDER>`,
`<CMA LICENCE NO. PLACEHOLDER>`, `<REGISTERED VALUER>`).

---

## Documentation

| Document | What it covers |
| --- | --- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layers, the ledger, posting rules, the request lifecycle, where each rule is enforced |
| [`docs/CMA_CONTROLS.md`](docs/CMA_CONTROLS.md) | Every regulatory requirement mapped to the control that satisfies it, for compliance to sign off |
| [`docs/runbooks/go-live-migration.md`](docs/runbooks/go-live-migration.md) | Loading the opening balances on the day |
| [`docs/runbooks/month-end-close.md`](docs/runbooks/month-end-close.md) | The close, in order, per client |
| [`docs/runbooks/incident-and-data-breach.md`](docs/runbooks/incident-and-data-breach.md) | Containment and the 72-hour notification |
| [`docs/runbooks/backup-and-restore.md`](docs/runbooks/backup-and-restore.md) | Backups, the seven-year retention rule, and a tested restore |
| [`docs/STATUS.md`](docs/STATUS.md) | What is built, what is deliberately deferred |

## Repository layout

```
backend/
  app/
    config.py            settings, and every [CONFIRM] default
    db.py                engine, session, Money/Rate SQL types, append-only DDL
    models/              SQLAlchemy models, one module per area
    schemas/             Pydantic request and response models
    ledger/              posting rules as data, post() validation, balances, reversal
    services/            the business workflows
    api/                 routers: validate, call a service, map errors
    jobs/                the scheduled worker (daily accruals, month-end revaluation)
  alembic/versions/      0001_initial_schema.py — the whole schema and the triggers
  seed/                  chart of accounts, role mappings, the two go-live batches
  scripts/               seed.py, export_openapi.py
  tests/                 unit, property-based, golden-number and API tests
  openapi.json           committed; the frontend's types are generated from it
frontend/
  app/(auth)/login/      sign-in with the MFA step
  app/(app)/             every signed-in screen
  app/api/[...path]/     the BFF proxy: attaches the token, checks CSRF
  components/            money/, ui/, tables/, forms/, layout/
  lib/                   api client, session, permissions, formatters
  types/api.d.ts         generated from backend/openapi.json
  tests/unit/            Vitest
  tests/e2e/             Playwright: the four scenarios from section 12
docs/
docker-compose.yml
```

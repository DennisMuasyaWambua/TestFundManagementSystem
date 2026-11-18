# Status

What is built and verified, and what is deliberately not. Written so nobody has to
guess during a review or an inspection.

Last verified: all gates green — `ruff`, `ruff format`, `mypy --strict`, 87 backend
tests, 22 frontend unit tests, `tsc --noEmit`, `eslint`, `next build`.

---

## Delivered, by phase

| Phase | Backend | Frontend | Exit test |
| --- | --- | --- | --- |
| 0 · Foundations | Settings, engine, `Decimal`/`NUMERIC` money types, append-only triggers in the migration, audit service | App shell, Tailwind tokens, sidebar, BFF proxy, generated API types | ✅ CI green |
| 1 · Identity | Users, argon2id, lockout, TOTP MFA, 30-minute tokens with revocation, permission table, `/me` | Sign-in with the MFA step, password change, idle sign-out, role-aware navigation, user admin | ✅ Auth tests; the 401/403 matrix is generated from the permission table |
| 2 · Ledger core | Chart of accounts, role mapping, posting rules as data, `post()` validation, balances, reversal, period locks, FX rates and base amounts | Journal search and entry detail, FX rate grid | ✅ Property tests: balance, ownership, immutability |
| 3 · Clients | Clients, KYC, agreements, custody accounts, fees | Client list and detail with the onboarding gaps | ✅ Gates block instructions until complete |
| 4 · Opening balances | Batches, templates, staging, validation report, preview, maker–checker approval, posting, lock, initial reconciliation | Batch list, five-step wizard, approval screen | ✅ **G1, G2** |
| 5 · Instructions | Full lifecycle, gate checks, gap-free reference sequence, deterministic PDF letters, signed-scan upload, settlement posting | List with a signatory's own queue first, new-instruction wizard with live checks, detail with the stepper | ✅ Instruction rules; the PDF hash test |
| 6 · Holdings and receipts | Receipts, maturities, repayments, rent, tenant deposits, write-off, true-ups | Holdings list and detail, receipt forms | ✅ **G3, G5** |
| 7 · Accruals, fees, close | Accrual and fee engine, rent invoicing, month-end close, checklist, the scheduled worker | Close screen with the checklist, dashboard | ✅ **G3, G4**; re-runs are no-ops |
| 8 · Currencies | FX revaluation, FX conversion instruction | Currency in forms and reports | ✅ **G6, G7** |
| 9 · Valuations | Propose and approve, fair value postings, revaluation on disposal | Valuations screen, holding valuation panel | ✅ **G8, G9** |
| 10 · Reconciliation | Custodian balances and positions, runs with segregation of duties | Reconciliation screen with break highlighting and run history | ✅ Break detection; a signatory is barred |
| 11 · Reporting | Trial balance, balance sheet, profit and loss, client statement with PDF, portfolio summary with XLSX, dashboard | Dashboard, statements, reports | ✅ A = B in every scenario |

All nine golden numbers reproduce to the cent (`pytest -m golden`).

### Also delivered

- **Migration** — one Alembic revision building all 26 tables and installing the
  append-only triggers, tested up, down and up again (on PostgreSQL in CI).
- **Committed OpenAPI** — `backend/openapi.json`, 77 paths; the frontend's types are
  generated from it and CI fails if either is stale.
- **The worker** — daily accruals and the month-end revaluation, idempotent, audited,
  and isolated per client so one client's bad data cannot stop the rest.
- **Docker Compose** — PostgreSQL, Redis, the API, the worker and the web app, with
  the migration and the seed run on the way up.
- **Seed** — the chart of accounts (70 accounts), 36 role mappings, 7 starter users,
  and the two go-live mandates with their four custody accounts.
- **Documentation** — architecture, the CMA control map, four runbooks, and the
  open-decisions table in the README.

### From phase 12

| Item | Status |
| --- | --- |
| Related-party limit check | ✅ Built — a gate check at instruction creation, against `related_party_limit_pct` |
| Per-client access control | ✅ Built — `user_client_access` narrows every read and write |
| Audit of statement reads | ✅ Built — `STATEMENT_VIEWED` |
| Accessibility | ✅ Built in: no colour-only meaning, real tables with scoped headers, labelled inputs, visible focus, 44 px targets, contrast ratios recorded in `globals.css`. **Not independently audited** |
| Backup and retention runbook | ✅ Written, including the restore drill |
| Complaints register | ❌ Not built — v2 |
| Load test | ❌ Not run |
| OWASP ASVS L2 review and penetration test | ❌ Not done |

---

## Not built, and why

Each of these is a deliberate scope decision, not an oversight.

| Not built | Why | What stands in |
| --- | --- | --- |
| **Complaints register** (CoB reg 16) | Marked v2 in the specification | The firm's existing complaints process |
| **Shariah purification** of non-compliant income | Open decision 14: the Shariah adviser has not stated a requirement | — |
| **Custodian statement import** from MT940 or bank APIs | Open decision 12: the formats have not been supplied | Statements are keyed on `/reconciliation`, or loaded as CSV in a migration batch |
| **Sanctions and PEP screening, FRC reporting** | These belong to the AML process, not a fund accounting system | KYC status and AML risk rating are recorded and gate every instruction |
| **The related-party register** | Deciding which counterparties are related is a firm judgement | The flag is honoured and the 10% limit checked when an instruction is raised |
| **SSO (OIDC)** | Not required for go-live | The token layer is built so SSO can replace passwords without touching the authorisation model |
| **Celery** | APScheduler is the specification's v1 option and needs no broker | Redis is in Compose, and the jobs are plain functions, so Celery is a drop-in later |
| **Load test, penetration test, ASVS L2 review** | Hardening phase; they need a deployed environment | The controls are built and unit-tested; they are not independently verified |

---

## Things to know before go-live

**Blocking, and not solvable in code:**

1. **Per-deposit accrued profit** (open decision 3). Rayan's 16,408.80 is a total, and
   Taaj's Wakala breakdown is missing entirely. Accrued profit must be per holding,
   because each holding's accrued balance has to reach exactly zero at its own
   maturity. The pro-rata split is available but it is a labelled placeholder that
   needs written acknowledgement.
2. **The Taaj difference of 516,745.92.** The batch posts it to suspense (1390) and
   **holds every Taaj statement** until a correcting entry clears it. Taaj cannot be
   sent a statement before then.
3. **The letterhead placeholders** (open decision 13). `<ADDRESS PLACEHOLDER>`,
   `<CMA LICENCE NO. PLACEHOLDER>` and the signatory titles appear on every instruction
   letter until they are configured. A custodian will reject a letter carrying them.
4. **Finance must approve accounts 1231, 1261, 4230 and 5350** (open decision 9). They
   exist and are flagged `is_proposed`; the fair value postings depend on them.

**Operational:**

5. Signatories, finance and administrators must enrol an authenticator before they can
   approve anything.
6. Every starter user's temporary password must be changed at first sign-in.
7. The worker must be running from go-live, or accruals will not post overnight.
8. The restore drill must be completed and signed before go-live, not after.

---

## Known limitations

- **The test suite runs on SQLite** for speed, with money stored as scaled integers so
  sums stay exact. CI runs the migration and the schema and append-only assertions
  against PostgreSQL 16, but the golden-number tests themselves run on SQLite. Running
  the whole suite against PostgreSQL nightly would close that gap.
- **The Playwright scenarios skip rather than fail** when the database they find is not
  in the state they expect (the go-live batches already posted, say). That keeps CI
  honest about ordering but means a green e2e run should be read alongside its output.
- **`outputFileTracingRoot` is not set** in `next.config.ts`: setting it triggers a
  `/_not-found` invariant in Next 15.5. The consequence is a warning when a stray
  lockfile sits above the repository, which does not occur in the Docker build.
- **No pagination on a few list screens.** Holdings, instructions and valuations fetch
  up to 500 rows and filter in the browser. Fine for two mandates; it needs server-side
  paging before the client count grows.

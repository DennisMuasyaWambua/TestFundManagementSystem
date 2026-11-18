# CMA control map

A living map from each regulatory requirement to the control that satisfies it and the
code that implements it. **Compliance confirms each row** in the last column; a row is
not signed off until compliance has seen the control working, not merely read about it.

Sources: Capital Markets (Conduct of Business) (Market Intermediaries) Regulations
2011 ("CoB"); Capital Markets (Licensing Requirements) (General) Regulations 2025
("Licensing"); CMA AML/CFT Guidelines; Data Protection Act 2019 ("DPA").

| # | Requirement | Source | Control in this system | Evidence | Confirmed |
| --- | --- | --- | --- | --- | --- |
| 1 | Client funds held in trust, not the firm's assets | CoB reg 28 | Client capital and profit are **liabilities** per client (2110/2210, 2120/2220). Firm equity accounts (3110–3130) are rejected outright by `post()` for any client line. Trust wording on every letter and statement. | `app/ledger/posting.py` (EQUITY check), `tests/test_ledger_core.py` | ☐ |
| 2 | Separate client accounts; a custodian account per client | CoB reg 29(1)–(2); Licensing reg 42(1)(c) | `custody_accounts` is per client, per currency, per custodian. A client-owned account rejects another client's line. | `app/ledger/posting.py` (ownership check), `tests/test_ledger_properties.py` | ☐ |
| 3 | One client's money never used for another | CoB reg 30(1)(c) | Cash-available is computed per custody account: ledger balance less every instruction already pending, approved or sent. Ledger ownership checks make cross-client posting impossible. | `app/services/instructions.py`, `tests/test_instructions.py` | ☐ |
| 4 | Withdrawals only on the client's written instruction | CoB reg 30(2), 31(6) | `client_instruction_ref` is **mandatory** on `PAY_CLIENT_PROFIT` and `RETURN_CAPITAL`; the instruction cannot be created without it and it is printed on the letter. | `app/services/instructions.py`, `/instructions/new` | ☐ |
| 5 | Custodian appointed in writing; acts only on proper instructions | Licensing reg 42(1)(d), 43 | The custody agreement reference gates instruction creation. Maker plus **two** signatories, neither the maker. The letter's SHA-256 and the signed scan's SHA-256 are both stored. Settlement is booked only on the custodian's confirmation, for exactly the instructed amount. | `app/services/instructions.py`, `app/services/letters.py` | ☐ |
| 6 | A written client agreement before any service | CoB reg 13 | `agreement_ref` and `agreement_date` gate instruction creation; the gap is listed on the client screen until supplied. | `app/services/clients.py` (onboarding gaps) | ☐ |
| 7 | KYC and AML | CoB reg 4; AML/CFT Guidelines | KYC status must be APPROVED before any instruction. AML risk rating recorded by compliance. **Sanctions screening and FRC reporting remain in the firm's AML process, not this system.** | `app/services/clients.py`, `/clients/[id]` | ☐ |
| 8 | Daily client account reconciliation, **not** by the payment authoriser | CoB reg 29(5)–(7) | Daily cash reconciliation per custody account in its own currency. `RECONCILIATION_RUN` is granted to FINANCE and COMPLIANCE only — **a SIGNATORY is barred**. Each run stores who performed it and when. | `app/services/permissions.py`, `app/services/reconciliation.py`, `tests/test_permissions_matrix.py` | ☐ |
| 9 | Monthly client asset reconciliation | CoB reg 31(3)–(4) | Position reconciliation per holding against the custodian's report; Sukuk compared on nominal. Breaks surface on the dashboard until cleared, and block the month-end close unless overridden with a written reason. | `app/services/reconciliation.py`, `app/services/closing.py` | ☐ |
| 10 | Proper records, daily, traceable to settlement; IFRS | CoB regs 32–35 | Double-entry ledger; every entry links to its instruction, migration batch or reversal. IAS 21: every line carries its rate and base amount, with month-end revaluation. Fair value via adjustment accounts, so cost is never overwritten. | `app/ledger/`, `app/services/fx.py`, `app/services/valuation.py` | ☐ |
| 11 | Records kept at least 7 years | CoB reg 36; AML Guidelines | Database triggers reject UPDATE and DELETE on `journal_entries`, `journal_lines` and `audit_log`. No hard deletes of business data anywhere; users and reference data are soft-deactivated. Retention and restore in the backup runbook. | `alembic/versions/0001_initial_schema.py`, `tests/test_migrations.py`, `docs/runbooks/backup-and-restore.md` | ☐ |
| 12 | Fund manager portfolio reports — monthly, quarterly within 15 days, half-yearly within 30, annual with the number of clients | Licensing reg 40(1) | Portfolio summary report with the client count, per client and asset class, plus cash at custodians; XLSX export. The reporting rhythm is shown as presets on `/reports`. | `app/services/reports.py`, `/reports` | ☐ |
| 13 | Related-company investments ≤ 10% of funds managed | Licensing reg 39(3) | `holdings.related_party` flag; the limit is checked when an instruction is created and the holding is flagged on screen. **The counterparty register that decides what is "related" is maintained outside this system.** | `app/services/instructions.py`, `related_party_limit_pct` | ☐ |
| 14 | Confidentiality and access control | CoB reg 15 | Own user store with argon2id hashes, lockout, TOTP MFA and 30-minute tokens. Role-based permissions enforced in the API. Optional `user_client_access` restricts a user to named clients for every read and write. Statement and report reads are audited. | `app/services/auth.py`, `app/services/permissions.py` | ☐ |
| 15 | Complaints register | CoB reg 16 | **Not built.** Deferred to v2 and recorded as such in `docs/STATUS.md`. | — | ☐ |
| 16 | Data protection by design; breach notice within 72 hours | DPA 2019 ss 41, 43 | TLS in transit; database and file store encrypted at rest; TOTP secrets encrypted with a key from the environment; secrets never in the repository. Notification procedure in the incident runbook. | `app/services/auth.py`, `docs/runbooks/incident-and-data-breach.md` | ☐ |
| 17 | Shariah approval of every investment | Mandate | `shariah_cert_ref` is required on every investment instruction, carried onto the holding, printed on the letter, and validated on every migrated holding. | `app/services/instructions.py`, `app/services/opening_balances.py` | ☐ |

---

## The segregation-of-duties matrix

Enforced in `app/services/permissions.py`. The 401/403 contract test is generated from
this same table, so the API and this document cannot disagree.

| Action | MAKER | SIGNATORY | FINANCE | COMPLIANCE | ADMIN |
| --- | :-: | :-: | :-: | :-: | :-: |
| Create an instruction | ✓ | | | | |
| Approve or reject an instruction (never their own) | | ✓ | | | |
| Mark sent, record settlement | ✓ | | ✓ | | |
| Record receipts (money in) | ✓ | | ✓ | | |
| Accruals, FX rates, month-end close, write-off | | | ✓ | | |
| Propose a valuation | ✓ | | ✓ | | |
| Approve a valuation (never their own) | | ✓ | ✓ | | |
| Opening balances: prepare | | | ✓ | | |
| Opening balances: approve (never their own) | | ✓ | ✓ | | |
| Record custodian statements | | | ✓ | ✓ | |
| Run the reconciliation | | | ✓ | ✓ | |
| View reports and statements | ✓ | ✓ | ✓ | ✓ | |
| View the audit log | | | | ✓ | ✓ |
| Manage users | | | | | ✓ |
| Client onboarding records | | | ✓ | ✓ | |

**ADMIN has no authority over money at all.** An administrator creates and disables
accounts; they cannot raise, approve, send or settle anything, and they cannot see a
client statement.

### The four maker–checker gates

| What | Prepared by | Approved by | Enforced in |
| --- | --- | --- | --- |
| A custody instruction | MAKER | **two** SIGNATORYs, neither the maker, and neither twice | `app/services/instructions.py` |
| A valuation | MAKER or FINANCE | a different FINANCE or SIGNATORY | `app/services/valuation.py` |
| An opening balance batch | FINANCE | a different FINANCE or SIGNATORY | `app/services/opening_balances.py` |
| A manual journal | FINANCE | a different FINANCE | `app/services/manual_journals.py` |

---

## What this system does **not** do

Stated plainly so nobody assumes otherwise during an inspection:

- **Sanctions and PEP screening, and FRC reporting** — the AML process, not this system.
- **The complaints register** (CoB reg 16) — deferred to v2.
- **Shariah purification of non-compliant income** — not built; awaiting the Shariah
  adviser's requirement.
- **Automated custodian statement feeds** (MT940, bank APIs) — statements are keyed or
  loaded from CSV.
- **Deciding which counterparties are related parties** — the flag is honoured and the
  limit checked, but the register is maintained elsewhere.
- **A penetration test and an OWASP ASVS L2 review** — scheduled for the hardening
  phase; the controls above are built but not yet independently tested.

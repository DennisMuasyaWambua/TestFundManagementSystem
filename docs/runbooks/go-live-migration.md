# Runbook: go-live opening balance migration

Loading each client's existing position as at close of business on the cutover date.
This happens **once per client**. Afterwards nothing can be posted on or before the
cutover date, so getting it wrong is expensive to unwind — a posted batch can only be
undone by a reversal batch, approved the same way.

**Who:** a FINANCE preparer and a different FINANCE or SIGNATORY approver.
**How long:** allow half a day per client, most of it in validation.

---

## Before the day

- [ ] **Agree the cutover date** with finance. A month-end is best. Every holding
      being loaded must still be live on that date — the batch refuses a holding whose
      maturity is on or before the cutover. *(For the Rayan deposits, which mature
      between 25 May and 14 August 2026, that means a cutover between 1 January and
      24 May 2026.)*
- [ ] **Decide the current-year profit treatment** (open decision 2). The default
      loads profit brought forward, current-year profit and profit paid as three lines
      on the client profit account, so the new profit and loss account starts at zero.
      Choosing `INCLUDE_PL` instead loads year-to-date income and expense totals.
- [ ] **Obtain the accrued profit *per deposit*** (open decision 3). A single total is
      not enough: the 1310 lines must each carry a holding id, because each holding's
      accrued balance has to reach exactly zero at its own maturity. If only a total
      is available, the pro-rata split can be used — but it is a clearly labelled
      placeholder that raises a warning requiring written acknowledgement, and it stays
      an open decision until the custodians confirm the real breakdown.
- [ ] **Enter the FX rate for the cutover date** for every non-base currency on
      `/fx-rates`. A posting with no rate on or before its date is refused outright.
- [ ] **Confirm each client is fully onboarded**: KYC approved, agreement reference and
      date, custody accounts with their custody agreement references, and the fee basis
      per asset class. `/clients/[id]` lists any gap.
- [ ] **Get the custodian statements** as at the cutover date — both cash balances and
      position reports. These are not optional: a difference against them is an
      **error** that blocks the batch, not a warning.
- [ ] **Take a backup** and verify it restores (see the backup runbook). This is the
      last clean point.

## The four CSVs

Templates download from the wizard, or at
`/api/v1/opening-balances/templates/<name>.csv`. UTF-8, one batch per client.

| File | One row per | Notes |
| --- | --- | --- |
| `holdings.csv` | investment held at cutover | Wakala and Sukuk need a rate, a start date and a maturity; every row needs a Shariah reference; the currency must match its custody account's |
| `lines.csv` | journal line (debit **or** credit, not both) | Debits must equal credits per currency. Every sub-ledger line carries a holding id |
| `custodian_balances.csv` | custody account | `custody_account,as_of,balance,statement_ref` |
| `custodian_positions.csv` | holding | `holding_id,as_of,amount,statement_ref` |

The committed examples under `backend/seed/opening_balances/` are the two go-live
batches with the figures finance supplied.

---

## On the day

### 1. Stage the batch — FINANCE preparer

1. `/migration/new`.
2. Choose the client, the cutover date and the profit treatment. Tick the pro-rata
   accrual split **only** if finance supplied a single total.
3. Upload all four CSVs. Each is stored with its SHA-256 before a row is read; the
   wizard shows the hash so you can confirm the file you picked is the file stored.
4. The rows go to staging tables. **Nothing touches the ledger yet.**

### 2. Validate

Upload-and-validate runs every check. **Errors block; warnings need written
acknowledgement.**

What it checks:

- every account code exists, is postable and active, and client-owned accounts belong
  to this client; profit-and-loss accounts only if the treatment allows them;
- every sub-ledger line has a holding id that exists in `holdings.csv`, and every
  holding has its investment line;
- per holding: the investment line equals the cost; Wakala and Sukuk have a rate, a
  start and a maturity; the maturity is after the cutover; a Shariah reference is
  present; the currency matches the custody account;
- accrued profit is **per holding**;
- debits equal credits per currency, and base amounts balance at the cutover rate;
- **reasonableness**: each deposit's profit is recomputed from its start date to the
  cutover and compared with the figure supplied. A difference above 1% or 1.00 is a
  warning — investigate before acknowledging it;
- **the statement test**: client capital plus client profit (A) must equal assets less
  liabilities (B). If it does not, the batch is blocked unless the difference is put on
  suspense (1390) with a reason, which is then a warning that must be acknowledged and
  is reported on the dashboard until cleared;
- **the custodian check**: cash and positions must equal the custodian's own figures.
  A difference here is an **error**. Resolve it with the custodian; do not load around it.

Correct the CSVs and re-upload until there are no errors. Acknowledge any warning in
writing, saying what you are acknowledging and why it is acceptable — the approver
reads this.

### 3. Preview and submit

Read the preview properly before submitting:

- the journal exactly as it will post, grouped by account, with totals;
- debits equal credits;
- Section A and Section B, and whether they will match;
- the holdings to be created, with each one's recomputed accrual beside the figure
  supplied;
- the custodian comparison.

Then submit. The batch becomes SUBMITTED and waits for someone else.

### 4. Approve — a different FINANCE or SIGNATORY

The preparer **cannot** approve; the API refuses it. The approver sees the same
preview read-only, plus every warning and its acknowledgement.

Approving does all of this in **one transaction**:

1. creates the holdings as ACTIVE, with `accrual_start = cutover + 1 day` and each
   one's opening accrued profit from its own 1310 line;
2. posts **one** `OPENING_BALANCE` entry dated the cutover date, carrying the batch id;
3. records the custodian balances and positions;
4. runs the reconciliation for the cutover date;
5. **sets the client's period lock to the cutover date**;
6. audits all of it.

If anything fails, nothing is saved.

### 5. Verify

- [ ] The batch shows POSTED with its journal entry number.
- [ ] `/clients/[id]/statement` for the cutover date reconciles (A = B) — or shows the
      held banner if the difference went to suspense.
- [ ] `/dashboard` shows the expected assets under management.
- [ ] `/reconciliation` shows no break at the cutover date.
- [ ] `/reports` trial balance balances.
- [ ] The period lock is the cutover date on `/clients/[id]`.

**Expected figures for the two go-live batches:**

| | Rayan | Taaj |
| --- | --- | --- |
| Total debits = credits | 5,619,061.17 | 7,614,827.62 |
| Owed to the client (A) | 5,490,667.23 | 7,498,198.90 |
| Net holdings (B) | 5,490,667.23 | 6,981,452.98 + 516,745.92 suspense |
| Statement | reconciles | **held** until suspense is cleared |

---

## Afterwards

- **Accrual continuity.** Opening accrued profit covers every day up to and including
  the cutover. The system accrues from the next day, so profit to date is
  `opening_accrued + Σ (outstanding × rate / day_basis)` from `accrual_start`. No day
  is counted twice and none is missed — `tests/test_golden_migration.py` asserts this.
  At maturity, any difference between the bank's profit figure and the accrued balance
  is booked as a true-up, so each holding's accrued balance ends at exactly zero.
- **The Taaj suspense balance** of 516,745.92 must be cleared by a correcting entry
  (a manual journal, maker–checker). Until then Taaj statements are held and the
  dashboard carries the alert. Do not issue a Taaj statement with the difference on it.
- **Start the worker** so the daily accrual runs from the next night.

## If it goes wrong

| Problem | What to do |
| --- | --- |
| Errors you cannot clear | Leave the batch unsubmitted. Nothing is in the ledger; fix the CSVs and re-upload. |
| Rejected by the approver | The reason is on the batch. Correct and resubmit, or start a new batch. |
| Posted, then found wrong | It cannot be edited. Prepare a **reversal batch** and have it approved the same way, then load a corrected batch. Raise it with finance and compliance first. |
| Posted with the wrong cutover | The period is locked at that date. Reverse as above; the lock moves with the corrected batch. |

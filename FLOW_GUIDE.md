# End-to-end flow: taking a client from zero to a closed month

This is the story of one client's money moving through the system, start to finish,
in the order it actually happens — not a screen-by-screen reference (that's
[`tutorial.md`](tutorial.md)) but the *sequence*: who does what, in what order, and
why each step has to wait for the one before it.

We'll walk a single worked example throughout — a new USD Wakala deposit of
1,000,000.00 at 4.25%, running 1 January to 14 August — the same numbers as golden
scenario **G3** in the README, so every figure below is one you can check against the
test suite. Real client names used are the two go-live mandates, **Rayan** and
**Taaj**; everything else is this guide's own walk-through.

Five people appear in this story, each signed in as a different seeded user:
`admin`, `compliance`, `fin.head` (or `fin.officer`), `ops.maker`, and the two
signatories `sig.one` / `sig.two`. That separation is not incidental — it's the whole
point of the system. No single login can both raise a payment and approve it.

---

## Stage 0 — Before anything else: signing in

1. Open the web app and sign in with your username and temporary password.
2. You're forced to **change your password** immediately (this is universal, not
   role-specific).
3. If your role is SIGNATORY, FINANCE or ADMIN, you're then walked through
   **enrolling an authenticator app** — a QR code appears exactly once. Scan it now;
   if you navigate away before scanning it, finance or admin has to reset your MFA to
   show it again.
4. You land on `/dashboard` — empty, for a brand-new client, until Stage 1 is done.

Nobody beyond this point can touch money until the steps below happen in order.

---

## Stage 1 — Client onboarding (nobody moves money yet)

This stage exists because three separate controls have to be satisfied before an
instruction is even *allowed* to be created — one by finance, one by compliance, and
the agreement itself. Miss any one and the gate at Stage 4 will refuse you, with a
plain-language reason.

1. **`admin` or `fin.head`** creates the client record at `/clients` → new client:
   legal name, base currency (USD for both go-live mandates), the signed investment
   management agreement's reference and date, and the final withholding tax rate.
   The client starts with KYC status `PENDING` — nothing can happen yet.
2. **`compliance`** opens the new client and records KYC: status and AML risk
   rating. Setting status to `APPROVED` is what actually unblocks the client.
3. **`fin.head`** adds the client's **custody accounts** — one per currency per
   custodian (e.g. "Absa Bank Kenya PLC, CR0012A, USD") — each carrying its own cash
   and Wakala ledger codes and its own custody agreement reference. This is also
   where the **management fee %** per asset class gets set (10% of income by
   default).
4. Check the gate: go to `/clients/[id]`. If KYC shows `APPROVED`, an agreement
   reference is on file, and the custody account has its own agreement reference,
   the client is live. If any one of those is missing, every later instruction for
   this client will be refused at creation with a message naming exactly which gate
   failed.

At this point the client exists but holds nothing — no cash, no investments, no
capital. There are two ways to give it a starting position, and they happen in
different order depending on whether this is a brand-new mandate or one being
migrated from an existing book of business.

---

## Stage 2 (only for a client being migrated — skip this for a brand-new one)

If the client already has a portfolio under some other system (this is exactly what
happened for Rayan and Taaj at go-live), their existing holdings have to be loaded as
a single, reconciled opening position **before** any new activity touches them.

1. **`fin.head`** opens `/migration/new`: picks the client, the **cutover date**
   (every holding being loaded must mature *after* this date), and the current-year
   profit treatment.
2. Downloads the two CSV templates, fills them from the old system's records and the
   custodian's own statements, and uploads them. Rows land in staging — **nothing
   touches the ledger yet.**
3. Clicks **Validate**. The system checks, among other things: every account code is
   real and belongs to this client; every holding has an accrued-profit line *per
   holding* (a lump total is rejected unless finance explicitly acknowledges the
   pro-rata placeholder in writing); debits equal credits; and — critically — that
   **capital + profit owed to the client (A) equals cash + investments + receivables
   − payables (B)**. If A ≠ B, the batch is blocked unless the gap is put on a
   clearly reasoned suspense line, which then holds that client's statements until
   someone clears it (this is exactly what happened to Taaj's 516,745.92 gap).
4. Preview shows the journal exactly as it will post, and the client statement
   exactly as it will read. `fin.head` submits it.
5. **A signatory, or finance's head, approves it** at `/migration/[id]`. (In a real
   deployment the approver can never be the same person who prepared it — on this
   test system that control is deliberately relaxed, so you can drive the whole
   lifecycle solo while you're learning it.)
6. On approval, in one transaction: the holdings are created (`ACTIVE`, accruing
   from the day *after* cutover), one `OPENING_BALANCE` journal entry posts dated the
   cutover date, and the custodian's own figures are recorded for reconciliation.
   (In a real deployment this would also lock the period through the cutover date;
   on this test system nothing is locked, so you can keep posting earlier-dated
   entries while exploring.)

For our worked G3 example, there's nothing to migrate — it's a brand-new deposit — so
we skip straight to Stage 3.

---

## Stage 3 — Money comes in: funding the mandate

Before the bank can place a deposit on the client's behalf, the client's own capital
has to be sitting in the custody account.

1. **`ops.maker`** (or `fin.officer`) goes to `/receipts/new`, picks **Client
   contribution**, selects the custody account (this fixes the currency — USD here),
   enters 1,000,000.00 and the custodian's own credit-advice reference.
2. The screen shows the journal it's about to post — `CLIENT_CONTRIBUTION`: debit
   the custody cash account, credit the client's capital account — before asking for
   confirmation. No signed letter is needed for money coming *in*.
3. Confirm. The dashboard's AUM figure for this client now reads 1,000,000.00, all
   of it sitting as cash, none of it yet invested.

---

## Stage 4 — Money goes out: placing the deposit

This is the part of the system built around a single sentence in the README: *the
bank never moves money itself.* Every outbound movement is a letter to the
custodian, and nothing is booked until the custodian confirms it actually happened.

1. **`ops.maker`** opens **`/instructions/new`**, picks **Place a Wakala deposit**,
   and the client. The form asks for the deal terms: counterparty (the bank taking
   the deposit), the amount (1,000,000.00), the profit rate (4.25%), the day basis
   (365), start and maturity dates, and the **Shariah approval reference** — every
   investment instruction needs one, with no exception.
3. A **live checks panel** on the same screen re-runs the API's own gate in real
   time as the form is filled in: is there 1,000,000.00 of *actual* cash available in
   that custody account (net of anything already pending against it)? Is KYC
   approved? Is the agreement on file? If any check is red, you'll see exactly which
   one before you waste time submitting.
4. Submit. The instruction is now **`PENDING_APPROVAL`**, reference
   `INS/2026/0001` (gap-free, sequential, per year). Its matching holding record
   exists already, but as `PENDING` — it isn't a real position yet.
5. **`sig.one`** signs in, sees it in their queue on `/instructions` (signatories see
   their own queue first), opens it, and **approves**.
6. **`sig.two`** — a *different* signatory, not `sig.one` again and not
   `ops.maker` — signs in and approves it too. The system refuses a second approval
   from the same person, and refuses the maker's own approval outright.
7. Two approvals move it to **`APPROVED`**. The system now generates the actual
   **instruction letter as a PDF** — the letterhead, the deal details, "do not act
   unless signed by two authorised signatories," both signature blocks — and stores
   its SHA-256 hash. The bytes are deterministic: the same instruction always
   produces the identical PDF, so the hash can always be checked against what gets
   downloaded.
8. Someone prints that letter. Both signatories **wet-sign it on paper**. It's
   scanned and **uploaded back onto the instruction** — this is what moves it to
   **`SENT`**, and the scan's own hash is stored alongside the letter's.
9. The letter physically goes to the custodian. Time passes — this is the one step
   that happens outside the system.
10. The custodian places the deposit and sends back a confirmation: their own
    reference, the date it settled, and the amount. **`fin.officer`** (or
    `ops.maker`) records that on the instruction — the amount must equal exactly
    what was instructed, no more, no less.
11. That recording moves the instruction to **`SETTLED`**, and *this* is the moment
    the ledger actually changes: `INVESTMENT_PLACED` posts (debit the Wakala deposit
    account, credit the custody cash account), the holding flips to `ACTIVE`, and its
    `accrual_start` is set to the settlement date. 1,000,000.00 moves from "cash" to
    "invested" on the dashboard.

---

## Stage 5 — Time passes: accrual

Nobody has to do anything here except make sure the worker is running — but it's
worth understanding what it's doing every night, because it's what makes every later
number correct.

- Every day, the scheduled job computes **profit to date** for the holding:
  outstanding principal × rate ÷ 365, summed from the day after settlement.
- It posts only the **difference** between that figure and what's already booked
  (`PROFIT_ACCRUED`) — so running it twice, or catching up after the job was down for
  a few days, never double-books anything.
- By the end of January, this deposit has accrued exactly **3,609.59** — the G3
  figure. You can see this running total on the holding's own page
  (`/holdings/[id]`) without waiting for anything to be paid.

If a rate is ever needed for a foreign-currency posting and `fin.head` hasn't
entered one for that date, every affected posting hard-stops with an error naming
the currency and date — there's no silent fallback to "yesterday's rate" or zero.

---

## Stage 6 — Profit matures and is received

1. On 14 August — 225 days after 1 January, the day basis the deal was struck on —
   the deposit matures. The accrual has by now reached its full **26,198.63**.
2. The custodian pays the bank **1,022,268.84**: the 1,000,000.00 principal plus
   26,198.63 profit, less 3,929.79 withholding tax deducted at source (15% of the
   gross profit).
3. **`fin.officer`** opens the holding and records the maturity at
   `/holdings/[id]`, quoting the custodian's own figures. The system posts
   `INVESTMENT_MATURED`: the custody cash account is debited for the net 1,022,268.84,
   the withholding-tax account carries the 3,929.79, and the investment and accrued
   profit for *this specific holding* both clear to zero. If the bank's actual figure
   differs even slightly from what the system had accrued, the difference is booked
   automatically as a true-up, so the holding's own accrued balance always lands at
   exactly zero — never a stray cent left over.
4. The **management fee**, 10% of the 26,198.63 income (2,619.86), was accruing in
   parallel the whole time on `FEE_ACCRUED`. It now sits as a payable, waiting to be
   paid out — a separate instruction, same lifecycle as Stage 4, type **Pay the
   management fee**.
5. The **client's profit**, after the fee, is **19,648.98** — but it hasn't reached
   the client yet. It's sitting as a liability (`CLIENT_PROFIT`) until it's actually
   paid out, which again is its own instruction (type **Pay profit to the client**),
   needing the client's own written request reference, going through the exact same
   maker → two signatories → letter → scan → settle lifecycle as Stage 4.
6. Once that profit payment and the fee payment both settle, every temporary account
   for this holding's cycle — the investment, the accrued income, the income account,
   the fee payable, the client's profit for this cycle — reads exactly zero. All
   that's left is cash and the client's original capital: the deal is fully closed
   out.

---

## Stage 7 — Valuation (only for Sukuk and property; not this Wakala example)

If instead of a Wakala deposit this had been a Sukuk holding or investment property,
there's one more recurring step: **`fin.officer`** or `ops.maker` proposes a
valuation (a Sukuk price per 100 of nominal, or a property value with the
independent valuer's report attached), and **a different** finance user or a
signatory approves it. Approval posts a `FAIR_VALUE_REVALUATION` that adjusts a
separate fair-value account — the original cost is never overwritten, so you can
always see what was paid against what it's currently worth.

---

## Stage 8 — Reconciliation (runs continuously, in parallel with everything above)

This doesn't wait for month-end — it runs daily for cash, monthly for positions, and
it's deliberately kept apart from the people who can authorise payments.

1. **`fin.officer` or `compliance`** — explicitly **never a signatory** — opens
   `/reconciliation`, enters (or imports) the custodian's statement balance for the
   custody account, and runs the comparison against the ledger's own cash balance.
2. Any difference is a **break**, shown on the dashboard until it's cleared with a
   correcting entry. A client whose reconciliation doesn't match has its statements
   held — exactly the state Taaj is in at go-live, by design, until the 516,745.92
   suspense gap is resolved.
3. Monthly, the same comparison runs for **positions** — does the custodian's own
   report of what they're holding for this client match what the ledger says?

---

## Stage 9 — Month-end close

Once a month, per client, finance runs the close.

1. **`fin.head`** opens `/close`, picks the client, and works through the
   checklist in order: **(1)** catch every accrual and rent invoice up to the period
   end, **(2)** revalue every foreign-currency balance at that day's closing rate,
   **(3)** the system blocks the close outright if reconciliation for the period end
   still has open breaks (an override with a written reason is the only way past
   this).
2. On confirming, `MONTH_END_CLOSE` posts: every income and expense account's
   balance since the last close is reversed out and the net result moves into
   `CLIENT_PROFIT` — so the client's profit balance is always the single source of
   truth for what they're owed, and this month's profit-and-loss report still shows
   the real income and costs (close entries are excluded from P&L views).
3. In a real deployment, the period would now be **locked** through the period end —
   nothing could ever be dated on or before that date again. On this test system
   that lock is deliberately not applied, so you can keep posting earlier-dated
   entries while you're exploring the flow.
4. Re-running the close for the same period re-sweeps it: since nothing new has
   accrued, there's no further profit to move, so it posts nothing twice in effect —
   it just isn't detected and short-circuited as "already closed" the way a real,
   locked deployment would.

---

## Stage 10 — Telling the client, and telling the regulator

1. **Anyone** can open `/clients/[id]/statement`, pick a period, and see Section A
   (capital + profit owed) laid out against Section B (cash + investments +
   receivables − payables) for that client. If they match, it shows a clean **A = B**
   badge; the statement can be downloaded as a PDF and marked **sent** (which is
   itself logged — who sent it, and when).
2. `/reports` produces the trial balance, balance sheet and profit-and-loss per
   mandate, and the **portfolio summary** the CMA requires across every client —
   exportable for the regulatory filing.
3. Every single thing that happened in every stage above — every sign-in, every
   approval, every posting, every failed attempt — is sitting in `/audit`, visible to
   compliance and admin, for at least seven years, and it cannot be edited or deleted.

---

## The shape of the whole thing, end to end

```
Onboard client ──▶ (migrate existing book, if any) ──▶ Fund it (contribution)
                                                              │
                                                              ▼
                                            Raise instruction (maker)
                                                              │
                                              2 signatories approve
                                                              │
                                               letter signed + scanned
                                                              │
                                             custodian confirms → SETTLED
                                                              │
                                                              ▼
                                        Holding ACTIVE, accrual starts
                                                              │
                                      (daily accrual, running quietly)
                                                              │
                                               Maturity / profit receipt
                                                              │
                                        Pay client profit + fee (→ Stage 4 again)
                                                              │
                        ┌─────────────────────────────────────┴───────────────┐
                        ▼                                                     ▼
            Reconciliation (continuous,                          Month-end close (monthly,
            kept apart from signatories)                         sweeps profit to the client)
                        │                                                     │
                        └───────────────────────┬─────────────────────────────┘
                                                 ▼
                              Client statement (A = B) + regulatory reports
```

Every arrow in that diagram is a control a real deployment relies on, not a
formality: a client can't be funded until onboarding clears; money can't leave
until two signatories say so; nothing posts until the custodian confirms it really
happened. (On this test system, two of the stricter ones — period locking and the
rule that the preparer can never also be the approver — are deliberately relaxed,
so you can drive the whole lifecycle solo while you're learning it; see
`ROLES_GUIDE.md` for exactly where.)

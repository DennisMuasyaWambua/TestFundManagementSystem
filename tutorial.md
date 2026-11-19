# Using the Shariah fund management system

A walkthrough for the people who will actually click through this system day to day:
operations (maker), signatories, finance, compliance and admin. For what the system is
and why it's built this way, see [`README.md`](README.md); this document is about
*using* it.

---

## 1. Signing in

Go to the web address you were given (e.g. `https://172.17.0.100:8543`).

1. Enter your username and password.
2. If your role requires multi-factor authentication (**signatories, finance and
   admins — always**), you'll be asked for a 6-digit code from an authenticator app
   (Google Authenticator, Authy, etc.) on every sign-in after you've enrolled.
3. **First sign-in**: you'll be forced to change your temporary password, and if your
   role needs MFA you'll be shown a QR code once — scan it with your authenticator app
   before you leave that screen, because it is not shown again. If you get locked out,
   it's 15 minutes after 5 wrong attempts.

You're signed out automatically after 30 minutes of inactivity (a warning appears at
25 minutes).

### Your role decides what you can see and do

| Role | What they're for | Can move money? |
| --- | --- | --- |
| **MAKER** (`ops.maker`) | Prepares custody instructions, records receipts | No — only prepares |
| **SIGNATORY** (`sig.one`, `sig.two`) | Approves instructions — two different signatories, never the person who prepared it | Only by approving |
| **FINANCE** (`fin.head`, `fin.officer`) | Accruals, FX rates, valuations, month-end close, opening balances, reconciliation | Yes, within controls |
| **COMPLIANCE** (`compliance`) | KYC, reconciliation, the audit log | No |
| **ADMIN** (`admin`) | Users and access only | **No — never money** |

The menu on the left only shows screens your role can use; the API enforces the same
rule even if you type a URL directly.

---

## 2. The dashboard (`/dashboard`)

Your landing page after sign-in. At a glance:

- **Assets under management**, reported in USD across every client.
- **Awaiting my action** — instructions sitting in your queue (e.g. a signatory with
  something to approve).
- **Reconciliation breaks** — differences between the ledger and the custodian's own
  records that still need clearing.
- **Next maturity** — the soonest deposit/Sukuk/financing coming due.
- A list of **instructions in progress**, **maturities within 90 days**, and any
  **client statements on hold** because their books don't yet balance (capital + profit
  owed ≠ cash + investments − payables — the "A = B" check).

Pick a different "as at" date to see the position on any past day.

---

## 3. Clients (`/clients`)

One row per **segregated mandate** — a client's own portfolio, kept completely apart
from every other client's money, cash and profit.

- Click a client to see its **custody accounts** (which bank holds its cash and
  investments), **KYC status**, **agreement reference**, and its **holdings**.
- A client can't have money moved for it until: KYC is `APPROVED`, it has a signed
  agreement reference on file, and its custody accounts have a custody agreement
  reference. New clients start `PENDING` until compliance approves KYC.
- `/clients/[id]/statement` shows the formal client statement: Section A (capital +
  profit owed to the client) against Section B (cash + investments + receivables −
  payables). They must match ("A = B"); if they don't, the statement shows a **held**
  banner with the reason, and can't be sent until it's cleared.

---

## 4. Holdings (`/holdings`)

Every investment the bank holds on behalf of every client — Wakala deposits, Sukuk,
private financing, investment property — in one list. Balances shown here (outstanding,
accrued profit, fair value adjustment) are read live from the ledger; they are never
stored on the holding itself, so they can't drift out of sync.

**Filters**: pick a client from the dropdown, an asset class, a status (pending / active
/ matured / written off / cancelled), and optionally a maturity window ("maturing
within 30/90/180 days" or an exact cutoff date) to see what's coming due.

Click into a holding (`/holdings/[id]`) to see its terms, its running balances, its
accrual history, any valuations, and every journal line ever posted against it. From
there (role permitting) you can record a profit receipt, a principal repayment, the
maturity/redemption, rent, a tenant deposit, or write it off, and propose a valuation.

---

## 5. Money coming in — receipts (`/receipts/new`)

Money arriving from a custodian needs **no signed letter** — only the custodian's own
credit advice reference as proof. Two flavours:

- **Client contribution**: new capital into a mandate. Pick the custody account (which
  sets the currency), the amount, and the advice reference.
- **A receipt against a holding**: profit paid on a Wakala/Sukuk/financing deal,
  a principal repayment, the final maturity, rent, or a tenant deposit — recorded from
  the holding's own page (`/holdings/[id]`), by MAKER or FINANCE.

Every receipt form shows you the journal entry that *will* post before you confirm it.

---

## 6. Money going out — custody instructions (`/instructions`)

**This is where custody instructions are created and where every outbound payment
starts.** The bank never moves client money itself — it sends the custodian a signed
letter, and nothing is booked until the custodian confirms the money actually moved.
New instructions are raised at **`/instructions/new`**, by a **MAKER**.

### The nine instruction types

Place a Wakala deposit · Buy Sukuk · Disburse private financing · Purchase investment
property · Pay profit to the client · Return capital to the client · Pay the management
fee · Pay the custody fee · Convert currency.

### How to raise one

1. Go to **Instructions → New instruction**.
2. Pick the type and the client.
3. Fill in the type-specific details (deal terms and the Shariah approval reference for
   an investment; the client's own written request reference for a profit payment or
   capital return; the target account, amount and agreed rate for an FX conversion).
4. A **live checks panel** re-asks the API's own gating rules as you type — cash
   actually available in that custody account, KYC approved, agreement on file, custody
   appointment on file, related-party limits — so you see why something is blocked
   *before* you submit, not after.
5. Submit. The instruction is now `PENDING_APPROVAL`.

### The lifecycle, step by step

```
PENDING_APPROVAL → APPROVED → SENT → SETTLED
       │               │
       └──→ REJECTED    └──→ (or CANCELLED, from either open state)
```

1. **PENDING_APPROVAL**: two different **signatories** must approve it — never the
   maker, and never the same signatory twice. (Rejecting requires a typed reason.)
2. **APPROVED**: the system generates the instruction letter as a PDF (the actual
   letter the bank sends the custodian), hashed so it can never be silently altered.
3. Someone prints it, gets it **wet-signed** by both signatories, and uploads a scan of
   the signed copy on the instruction's page. That moves it to **SENT**.
4. When the custodian confirms the money actually moved — quoting their own
   confirmation reference, the settled date, and the amount (which must equal exactly
   what was instructed) — FINANCE or the MAKER records that, and it becomes
   **SETTLED**. *Only now does it hit the ledger.*

Signatories see their own queue first on the Instructions screen. The instruction
detail page (`/instructions/[id]`) shows a stepper for where it is in this lifecycle,
the letter preview, and the actions available to you for its current state.

---

## 7. Opening balance migration (`/migration`) — go-live only

A one-off wizard that loads a client's existing holdings as at a cutover date, from the
old system and the custodian's own statements. Prepared by **FINANCE**, approved by a
**different** FINANCE head or a **SIGNATORY** (never the preparer). Nothing touches the
ledger until it's approved and posted; after posting, nothing can ever be dated on or
before that cutover date again.

You won't normally need this screen after go-live — it exists for bringing a new client
onto the system with a pre-existing book of business.

---

## 8. Valuations (`/valuations`) — Sukuk and property

Sukuk is priced per 100 of nominal; investment property is valued by an independent
valuer. Proposed by MAKER or FINANCE, approved by a *different* FINANCE or SIGNATORY.
Approval books the fair-value adjustment — the original cost is never overwritten, so
you can always see what was paid versus what it's worth now.

---

## 9. Exchange rates (`/fx-rates`) — FINANCE

Every journal line carries its own FX rate and base-currency amount, so FINANCE must
enter a daily rate for every foreign currency before anything in that currency can be
posted that day. A missing rate is a hard stop, not a guess.

---

## 10. Reconciliation (`/reconciliation`) — FINANCE or COMPLIANCE

Checks the bank's own ledger against what the custodian actually reports: cash
balances daily, investment positions monthly. **A signatory is deliberately barred from
running this** — the person who can authorise a payment must not be the person who
checks whether the money is really there. Breaks are highlighted and show on the
dashboard until someone clears them with a correcting entry.

---

## 11. Month-end close (`/close`) — FINANCE, per client

Runs, in order, for one client at a time: catch up every accrual and rent invoice to the
period end, revalue foreign currency at the closing rate, block if reconciliation has
unresolved breaks (unless overridden with a reason), then close the profit-and-loss
accounts into the client's profit balance and lock the period. Once a period is locked,
nothing can ever be posted on or before that date — a back-dated entry is refused
outright. Running it again for an already-closed period is a safe no-op.

---

## 12. Reports (`/reports`)

Trial balance, balance sheet and profit-and-loss per mandate, plus the portfolio
summary the CMA (the regulator) requires across every client. Exportable.

## 13. The journal (`/journal`) — FINANCE or COMPLIANCE

Every posting ever made, searchable by client, account, holding, date or event type.
**Nothing here can be edited or deleted** — that's enforced at the database level, not
just in the screen. A mistake is corrected by posting a reversal (a mirror-image entry)
plus a new, correct one — never by changing history. A manual journal entry can be
raised here too, but it needs a second FINANCE user to approve it before it posts.

## 14. Audit log (`/audit`) — COMPLIANCE or ADMIN

Every sign-in, failure, approval, state change and posting, kept for at least seven
years and never editable. Filter by user, entity or date range.

## 15. Users (`/admin/users`) — ADMIN only

Create accounts, assign a role, optionally restrict a user to specific clients,
disable an account, or reset someone's MFA. **Admin has no authority over money at
all** — it's a deliberately powerless role, by design, so that no single account can
both grant access and move funds.

## 16. Your profile (`/settings/profile`)

Change your password, and enrol or reset your authenticator app.

---

## Quick reference: who does what

| Task | Who |
| --- | --- |
| Raise a custody instruction | MAKER |
| Approve/reject an instruction (2 needed) | SIGNATORY |
| Record a receipt (money in) | MAKER or FINANCE |
| Mark an instruction sent / settled | MAKER or FINANCE |
| Enter FX rates, run accruals, month-end close, write off a holding | FINANCE |
| Propose a valuation | MAKER or FINANCE |
| Approve a valuation | SIGNATORY or FINANCE (not the proposer) |
| Run reconciliation | FINANCE or COMPLIANCE (never a signatory) |
| Record KYC | COMPLIANCE |
| View the audit log | COMPLIANCE or ADMIN |
| Manage user accounts | ADMIN |

## If something looks wrong

- **A number looks off**: check the holding's own page — every balance has its full
  journal history attached, so you can see exactly which postings produced it.
- **An instruction won't let you submit**: the live checks panel on the new-instruction
  screen tells you exactly which gate is failing (KYC, cash available, agreement on
  file, etc.) — fix that first.
- **A client's statement says "held"**: its books don't balance yet (A ≠ B); it will say
  why, and it can't be sent to the client until a correcting entry clears it.
- **You can't post something**: if the date falls on or before a month that's already
  closed for that client, it's locked by design — nothing can be posted into a closed
  period.

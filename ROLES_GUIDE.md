# What each role does, screen by screen

Five roles exist: **MAKER**, **SIGNATORY**, **FINANCE**, **COMPLIANCE**, **ADMIN**.
This maps every screen to exactly which roles can see it and which specific buttons,
tabs and forms on it each role gets — taken directly from the permission table in
`backend/app/services/permissions.py` and the gating in each screen's own code, not
guessed. Two things to hold in mind throughout:

- **The sidebar only hides what a role can't use — it's a courtesy, not the control.**
  The API enforces every one of these independently and answers 403 if the UI's own
  check was ever wrong, so nothing below is "security through hiding a button."
- **The same person never both prepares and approves.** This single rule is why
  several screens look different depending on whether you raised the thing in front
  of you or not, not just on your role.

The five roles, in one line each:

| Role | Seeded user | One-line job |
| --- | --- | --- |
| MAKER | `ops.maker` | Prepares instructions and records receipts — never approves |
| SIGNATORY | `sig.one`, `sig.two` | Approves instructions and valuations — never prepares |
| FINANCE | `fin.head`, `fin.officer` | Runs the books: accruals, FX, close, opening balances, most day-to-day money work |
| COMPLIANCE | `compliance` | KYC, reconciliation, the audit log — no money powers |
| ADMIN | `admin` | Users and access only — **explicitly no money powers at all** |

---

## The sidebar itself

What each role even sees in the left-hand menu:

| Section | MAKER | SIGNATORY | FINANCE | COMPLIANCE | ADMIN |
| --- | :-: | :-: | :-: | :-: | :-: |
| Dashboard, Clients, Holdings | ✓ | ✓ | ✓ | ✓ | ✓ |
| Custody instructions | ✓ | ✓ | ✓ | ✓ | ✓ |
| Record a receipt | ✓ | — | ✓ | — | — |
| Valuations | ✓ | ✓ | ✓ | ✓ | ✓ |
| Exchange rates | — | — | ✓ | — | — |
| Reconciliation | — | — | ✓ | ✓ | — |
| Month-end close | — | — | ✓ | — | — |
| Opening balances | — | ✓ | ✓ | — | — |
| Journal | — | — | ✓ | ✓ | — |
| Reports | ✓ | ✓ | ✓ | ✓ | — |
| Audit log | — | — | — | ✓ | ✓ |
| Users | — | — | — | — | ✓ |
| My profile | ✓ | ✓ | ✓ | ✓ | ✓ |

(Everyone sees "Custody instructions," "Valuations" and "Holdings" — what you can
*do* once you're on those screens is where the roles actually diverge, covered below.)

---

## Dashboard (`/dashboard`)

Identical content for every role — AUM, your own queue, reconciliation breaks, next
maturities, instructions in progress, statements on hold. The only role-specific
thing on it is **"Awaiting my action"**: for a SIGNATORY this is instructions waiting
on their signature; for FINANCE it can include accruals or valuations; for a MAKER
it's typically empty, since makers prepare rather than wait.

## Clients (`/clients`, `/clients/[id]`)

- **Everyone** can view the list and open a client's overview, custody accounts,
  fees, holdings and statement.
- **FINANCE or COMPLIANCE** (permission `CLIENT_ONBOARDING`) are the only roles who
  can edit the onboarding fields: create a client, add custody accounts, set fees,
  record KYC. In practice this splits further by convention: FINANCE creates the
  client and its custody accounts; COMPLIANCE is the one who actually sets KYC status
  to `APPROVED`.
- **FINANCE or COMPLIANCE** (permission `JOURNAL_VIEW`) see a **Journal** tab on a
  client's page that nobody else gets — MAKER, SIGNATORY and ADMIN don't see it at
  all.
- **ADMIN never touches a client record** — no money, no onboarding power, nothing.

## Holdings (`/holdings`, `/holdings/[id]`)

- **Everyone** sees the list, the filters (including the client dropdown), and a
  holding's terms, balances, accrual history and journal.
- The **"Record a movement" panel** on a holding's page is where roles genuinely
  split:
  - **MAKER or FINANCE** (`RECEIPT_RECORD`) get the buttons to record profit
    received, a principal repayment, the maturity, rent, or a tenant deposit —
    whichever apply to that asset class.
  - **FINANCE only** (`LEDGER_OPERATIONS`) additionally gets **"Write this financing
    off"** — the one destructive action on this screen, and it requires a typed
    reason.
  - **SIGNATORY, COMPLIANCE and ADMIN get none of these buttons** — the panel
    doesn't render at all for them; they can only look.
  - **Propose a valuation** (Sukuk/property holdings) appears for **MAKER or
    FINANCE** (`VALUATION_PROPOSE`).

## Recording a receipt (`/receipts/new`)

- Only **MAKER or FINANCE** (`RECEIPT_RECORD`) can reach this screen at all — it
  doesn't appear in SIGNATORY's, COMPLIANCE's or ADMIN's sidebar, and the API
  refuses the POST if they get there by URL.
- No distinction between MAKER and FINANCE here — both get the identical
  contribution and holding-receipt forms.

## Custody instructions (`/instructions`, `/instructions/new`, `/instructions/[id]`)

This is the screen where the roles are most sharply divided, because it's the one
place money actually leaves the building.

- **`/instructions/new` — raising one: MAKER only.** Nobody else can create an
  instruction; even FINANCE cannot (FINANCE's money powers are about postings and
  accruals, not instructing a custodian).
- **The list (`/instructions`) defaults differently per role**: a SIGNATORY lands on
  the "Awaiting approval" tab first — their queue, front and centre. Everyone else
  defaults to "In progress."
- **On an individual instruction**, the API computes exactly three booleans per
  viewer — `can_approve`, `can_dispatch`, `can_settle` — and the page only shows the
  matching button when true:
  - **Approve / Reject**: only a **SIGNATORY who has not already signed this
    instruction and is not the maker who prepared it**. `sig.one` and `sig.two` both
    need to act, and the system refuses a repeat signature from either of them.
  - **Cancel**: available while the instruction is still `PENDING_APPROVAL` or
    `APPROVED` — this isn't signatory-only, but it still goes through the API's own
    check of who is allowed to touch it.
  - **Mark sent** (upload the signed scan): **MAKER or FINANCE** (`INSTRUCTION_DISPATCH`).
  - **Record settlement** (the custodian's confirmation): also **MAKER or FINANCE**
    (`INSTRUCTION_DISPATCH`).
  - **Download the letter**: anyone, once it exists (from `APPROVED` onward).
  - **COMPLIANCE and ADMIN can see every instruction and its full history, but have
    no buttons on this screen at all** — pure read access.

## Valuations (`/valuations`)

- **Propose** (Sukuk price or property value): **MAKER or FINANCE**
  (`VALUATION_PROPOSE`) — reached from a holding's own page, not this list.
- **Approve or reject**: **FINANCE or SIGNATORY** (`VALUATION_APPROVE`) — and never
  the same user who proposed it. If you can't approve, the screen tells you so
  directly: *"Approving a valuation needs a finance or signatory role — and never
  the person who proposed it."*
- **COMPLIANCE and ADMIN**: view only, same as everyone, no action either way.

## Exchange rates (`/fx-rates`)

**FINANCE only** (`FX_RATES_MANAGE`) — this doesn't even appear in anyone else's
sidebar. Every other role is affected by missing rates (a posting hard-stops if
one's missing) but only finance can enter them.

## Reconciliation (`/reconciliation`)

- **Recording custodian statements**: **FINANCE or COMPLIANCE**
  (`CUSTODIAN_STATEMENT_RECORD`).
- **Running the comparison**: **FINANCE or COMPLIANCE** (`RECONCILIATION_RUN`) —
  and this is a deliberate, named exclusion: **a SIGNATORY is barred from running
  reconciliation**, specifically so the person who can authorise a payment is never
  also the person checking whether the custodian's own records agree with the
  ledger (CMA CoB reg 29(5)-(7)).
- **MAKER and ADMIN** don't see this screen at all.

## Month-end close (`/close`)

**FINANCE only** (`LEDGER_OPERATIONS`) — the checklist, the run buttons, and the
override-with-reason if reconciliation has open breaks. No other role can reach this
screen; the period lock it sets affects everyone's ability to post, but only FINANCE
can trigger it.

## Opening balance migration (`/migration`, `/migration/new`, `/migration/[id]`)

- **Preparing a batch** (`/migration/new`): **FINANCE only**
  (`OPENING_BALANCE_PREPARE`).
- **Approving or rejecting it** (`/migration/[id]`): **FINANCE or SIGNATORY**
  (`OPENING_BALANCE_APPROVE`) — and the API refuses an approval from the same user
  who prepared it, even if they're FINANCE too. In practice this means a *different*
  finance head, or either signatory.
- **The list itself** is visible to anyone who holds prepare or approve rights —
  MAKER, COMPLIANCE and ADMIN don't see it in the sidebar at all.

## Journal (`/journal`)

- **Viewing and searching**: **FINANCE or COMPLIANCE** (`JOURNAL_VIEW`) only —
  MAKER, SIGNATORY and ADMIN don't get this screen.
- **Reversing an entry**: **FINANCE only** (`LEDGER_OPERATIONS`), and only on an
  entry that isn't itself already a reversal.
- **Manual journal entries**: FINANCE prepares one, and it needs a **second,
  different FINANCE user** to approve it before it posts — maker-checker applied
  within a single role, not across roles, because this is the one workflow where
  the preparer and approver are deliberately drawn from the same permission group.

## Reports (`/reports`)

**MAKER, SIGNATORY, FINANCE and COMPLIANCE** can all view trial balance, balance
sheet, profit-and-loss and the CMA portfolio summary (`REPORTS_VIEW`). **ADMIN
cannot** — reporting is about the business the firm is managing, which an
admin-only, no-money-powers role has no reason to see.

## Audit log (`/audit`)

**COMPLIANCE or ADMIN only** (`AUDIT_VIEW`). This is the one screen ADMIN *does*
get real content on, consistent with admin's job being access and oversight, not
money.

## Users (`/admin/users`)

**ADMIN only** (`USERS_MANAGE`). Create an account with a temporary password,
assign a role, optionally restrict someone to named clients, disable an account, or
reset a user's MFA enrolment. No other role can reach this screen, and — worth
repeating, because it's the whole point of the role — **nothing here grants ADMIN
any authority over money.** Creating a FINANCE user doesn't let the admin act as
one.

## My profile (`/settings/profile`)

Identical for everyone: change your own password, enrol or reset your own
authenticator app. The only role-shaped difference is that SIGNATORY, FINANCE and
ADMIN are required to enrol MFA before they can act on anything; MAKER and
COMPLIANCE are not required to, though they can still choose to enrol.

---

## The permission table underneath all of this

Every gate above traces back to one table, enforced in the API (not the screen) —
reproduced here exactly as the backend defines it, since it's the actual source of
truth:

| Permission | MAKER | SIGNATORY | FINANCE | COMPLIANCE | ADMIN |
| --- | :-: | :-: | :-: | :-: | :-: |
| Create an instruction | ✓ | | | | |
| Approve / reject an instruction | | ✓ | | | |
| Mark sent / record settlement | ✓ | | ✓ | | |
| Record a receipt | ✓ | | ✓ | | |
| Accruals, FX rates, close, write-off, reverse a journal entry | | | ✓ | | |
| Propose a valuation | ✓ | | ✓ | | |
| Approve a valuation | | ✓ | ✓ | | |
| Prepare an opening balance batch | | | ✓ | | |
| Approve an opening balance batch | | ✓ | ✓ | | |
| Record a custodian statement | | | ✓ | ✓ | |
| Run reconciliation | | | ✓ | ✓ | |
| View reports and statements | ✓ | ✓ | ✓ | ✓ | |
| View the journal | | | ✓ | ✓ | |
| View the audit log | | | | ✓ | ✓ |
| Onboard a client / edit KYC | | | ✓ | ✓ | |
| Manage users | | | | | ✓ |

A blank cell isn't an oversight — it's load-bearing. The two gaps worth noticing
most: **nobody holds both "create an instruction" and "approve an instruction"**
(that's maker-checker, enforced structurally, not just by convention), and **ADMIN
has a blank row everywhere except user management** — by design, an administrator in
this system cannot move a single cent, no matter what else they can configure.

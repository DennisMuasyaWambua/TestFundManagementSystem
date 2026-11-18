# Runbook: month-end close

Closing a period for one client sweeps that period's income and costs to the client's
profit and **locks the period**: nothing can be posted on or before the closed date
afterwards. Several months can be closed in sequence.

**Who:** FINANCE. **When:** after the custodian statements for the period have arrived.
**How long:** minutes per client once the reconciliation is clean.

---

## Before you start

- [ ] Every receipt, instruction settlement and valuation for the period is recorded.
      Anything posted after the close needs a reversal in an open period instead.
- [ ] The **closing FX rate** for the period end is entered for every non-base
      currency (`/fx-rates`). Without it the revaluation cannot run.
- [ ] The custodian statements for the period end are keyed or loaded
      (`/reconciliation`), both cash and positions.
- [ ] Any valuation the checklist lists as due has been proposed **and approved** —
      approval is what posts the fair value adjustment, and a valuation sitting
      unapproved leaves the holding at cost.

## The order, which the system enforces

Work through the checklist on `/close?period_end=YYYY-MM-DD`, one card per client.

### 1. Accruals and rent

Accrues profit, invoices rent and charges management fees up to the period end.

- Profit to date is cumulative, so only the difference is posted. **Re-running is
  safe** and posts nothing the second time.
- Rent is invoiced on the first of each month from the month after acquisition or
  cutover, keyed on a unique reference per holding and month.
- Fees are a percentage of the income recognised **in the system** — so no fee is
  charged on profit that was accrued before cutover.
- Any holding whose terms are still a placeholder is **skipped** and listed. Supply its
  real terms before closing, or you are closing a month that under-accrues.

### 2. Exchange revaluation

Restates every foreign-currency balance sheet balance at the closing rate, except
client capital and client profit. The net goes to FX gain (4210) or FX loss (5320).

A balance whose own-currency amount is zero but whose base amount is not — the residue
after a maturity settled at a different rate — is cleared the same way. **That residue
is the realised gain or loss**; it is not an error.

### 3. Reconciliation

The close is **blocked** if the reconciliation for the period end has breaks.

Either clear the break — usually a missing statement, a value date difference or an
unrecorded receipt — or close with an override, which requires a written reason that
goes on the audit trail. Use the override when the break is understood and accepted,
not to get past something you have not investigated.

Remember the reconciliation cannot be run by a payment signatory (CoB reg 29(5)–(7)).
FINANCE or COMPLIANCE runs it.

### 4. Close and lock

Posts `MONTH_END_CLOSE` in base currency: each profit-and-loss account's base balance
since the last close is reversed out, and the net goes to the client's profit account.
Then the period lock moves to the period end.

Profit-and-loss **reports exclude the closing entry**, so each month still shows the
income it earned and the costs it bore.

---

## Afterwards

- [ ] `/clients/[id]/statement` for the period reconciles (A = B). If it does not, the
      statement is held and must not be sent — find the difference first.
- [ ] `/reports` trial balance balances; the profit and loss for the period looks right.
- [ ] Every profit-and-loss account is zero as at the period end (the close swept them).
- [ ] The locked-through date on `/clients/[id]` is the period end.
- [ ] Any suspense balance is still flagged on the dashboard — closing does not clear it.

Then: issue the client statements, and raise the profit and fee payouts through
`/instructions/new` if they are due. A fully matured deposit whose profit and fee have
been paid leaves only cash and the client's capital — every temporary account for that
cycle is zero.

## If it goes wrong

| Problem | What to do |
| --- | --- |
| "No rate for KES on 2026-02-28" | Enter the closing rate on `/fx-rates` and re-run the revaluation. |
| A break you cannot clear in time | Close with an override and a written reason naming what is unresolved and who is chasing it. Clear it next month. |
| Closed too early, before a receipt was recorded | The period is locked. Post the receipt in the **open** period with its true value date if the lock allows, or reverse the close entry and re-close — both are maker–checker actions. Tell finance before doing either. |
| A back-dated receipt is refused | That is the lock working. The message names the client and the date it is closed through. |
| An accrual posted twice | It cannot have. Accruals post the difference to a cumulative target; if a figure looks doubled, the holding's terms or its opening accrued figure is wrong, not the job. |

# Runbook: incident and data breach

Covers a suspected compromise of the system, the data in it, or a user's credentials.
Client money and client personal data are both in scope.

**The Data Protection Act 2019 (ss 41, 43) requires notification to the Office of the
Data Protection Commissioner within 72 hours** of becoming aware of a personal data
breach, and notification to affected data subjects where there is a real risk to them.
The clock starts at *awareness*, not at confirmation — so start the record immediately.

**Decide first:** is money at risk, is data at risk, or both? If money is at risk,
contain it before anything else — stopping an unconfirmed instruction is reversible,
and a payment is not.

---

## 0. Record the time

Write down the time you became aware, who reported it, and what they saw. Everything
after this is measured from that moment. Keep the record outside this system.

## 1. Contain — the first 30 minutes

**If a user's account may be compromised**

1. `/admin/users` → **Disable** the account. This revokes every token already issued
   to them immediately (the token version is bumped), so an attacker holding a valid
   token is signed out at once.
2. **Reset MFA** as well if the authenticator may be in someone else's hands.
3. `/audit` → filter by that user. Look for `LOGIN`, `LOGIN_FAILED`, instruction
   approvals, settlements and statement reads. Note everything they touched.

**If an unauthorised payment may have been instructed**

1. `/instructions` → check **Approved, not sent** and **Sent, not confirmed**.
2. **Cancel** anything not yet sent, with the reason.
3. For anything already sent, **telephone the custodian immediately** to stop it, using
   the contact on the custody agreement — not a number from an email. Follow up in
   writing.
4. Nothing settles without the custodian's confirmation, so an unconfirmed instruction
   has moved no money and posted nothing. Say so in the record: it limits the exposure.

**If the API or database may be compromised**

1. Take the API out of service (scale `api` and `web` to zero, or pull them from the
   load balancer). The ledger is append-only, so an attacker cannot alter history —
   but they can add to it.
2. Preserve evidence **before** restarting anything: snapshot the database, and copy
   the application and reverse-proxy logs somewhere the running system cannot write.
3. Rotate `FMS_SECRET_KEY`. This invalidates every access token in existence; everyone
   signs in again. Rotate database credentials and the file-store credentials too.
4. Do **not** restore from backup yet. A restore destroys the evidence of what happened
   and may reintroduce the hole.

## 2. Assess — the first 24 hours

Answer these in writing:

- **What was accessed?** The audit log records every state change, sign-in, failure,
  approval, posting and statement read, with who and when. It is append-only, so it
  can be relied on even if the attacker had application access.
- **Was any client's personal data involved?** Client legal names, agreement
  references, KYC status and risk ratings, and the custody account numbers. If yes,
  DPA notification is engaged.
- **Did any money move?** Compare the ledger against the custodians' records
  (`/reconciliation`) for every client, for every date in the window. A movement that
  the custodian confirmed but the ledger does not expect — or the reverse — is the
  signal. This is the authoritative check, because the custodian's record is
  independent of this system.
- **Is the ledger intact?** Run the trial balance and every client statement. Every
  entry balances and every statement has A = B, or something is wrong. The
  append-only triggers mean history cannot have been rewritten, only added to; a
  spurious entry can be reversed.
- **Which clients are affected, and are their mandates still segregated?** Check that
  no client's line sits on another's account (the ledger prevents it, but prove it).

## 3. Notify

| Who | When | What |
| --- | --- | --- |
| The firm's data protection officer and compliance | Immediately | Everything known so far |
| The Office of the Data Protection Commissioner | **Within 72 hours** of awareness, if personal data is involved | Nature of the breach, categories and approximate number of data subjects, likely consequences, measures taken |
| Affected clients | Without undue delay where there is a real risk to them | What happened, what it means for them, what they should do |
| The Capital Markets Authority | Per the firm's regulatory reporting obligations — ask compliance, do not decide alone | |
| The affected custodian | Immediately, if any instruction or custody account is implicated | |

If the facts are incomplete at 72 hours, **notify anyway** with what is known and say
that it is provisional. A late notification is a separate breach.

## 4. Recover

1. Close the hole. Patch, change the configuration, revoke the access — whatever it was.
2. Rotate every secret that could have been exposed: `FMS_SECRET_KEY`, database
   credentials, file-store credentials, and the TOTP encryption key *(rotating that
   last one requires re-enrolment for every user, so plan it)*.
3. Force a password change for anyone affected: `/admin/users` → **Reset password**,
   which issues a temporary password that must be changed at first sign-in.
4. Restore service. Restore from backup **only** if data was destroyed or corrupted,
   and only after the evidence is preserved — see the backup runbook.
5. Reverse any spurious ledger entry (`/journal` → **Reverse**, with the reason) and
   post the correct one. Never edit; the database will not allow it.
6. Reconcile every affected client against the custodians again, and confirm A = B for
   each.

## 5. Afterwards

- Write it up: timeline, cause, what was affected, what was done, what will change.
- Keep the record for seven years with the other business records.
- Fix the cause, not just the symptom. If a control failed, add a test for it — that is
  what stops the same incident twice.
- Review who had access to what. If someone had more than they needed, narrow it
  (`user_client_access` restricts a user to named clients).

---

## What is already in place

Worth knowing before an incident, and worth saying during one:

- **The ledger cannot be rewritten.** Database triggers reject UPDATE and DELETE on the
  journal and the audit log. An attacker with application access can add entries, not
  alter or erase them.
- **No money moves without the custodian.** Outgoing money requires a letter signed by
  two authorised signatories and the custodian's confirmation, for exactly the
  instructed amount. Application access alone cannot move client money.
- **Tokens are short-lived and revocable.** 30 minutes, and disabling a user, changing
  their password or rotating the secret key revokes every token already issued.
- **The token never reaches the browser.** It lives in an httpOnly, `SameSite=Strict`
  cookie, so page script cannot read it.
- **MFA is mandatory** for signatories, finance and administrators.
- **Lockout** after five failed attempts for fifteen minutes, with every failure
  audited.
- **The audit log is independent** of the data it describes and cannot be edited.

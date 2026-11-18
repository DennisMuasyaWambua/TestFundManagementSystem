# Runbook: backup, retention and restore

Business records must be kept for **at least seven years** (CoB reg 36; AML/CFT
Guidelines). Nothing in this system is ever hard-deleted — the journal and the audit
log reject UPDATE and DELETE at the database level, and users and reference data are
soft-deactivated — so the retention obligation falls almost entirely on the backups.

**A backup you have never restored is not a backup.** The restore drill below is the
part that matters.

---

## What has to be backed up

| What | Where | Why it cannot be recreated |
| --- | --- | --- |
| The PostgreSQL database | `postgres` volume | The ledger, every balance, the audit log, every approval |
| The file store | `file-store` volume (`FMS_FILE_STORE_PATH`) | **Signed letter scans**, custodian statements, valuer reports, migration CSVs — the evidence behind the postings. The hashes are in the database; the bytes are only here |
| `FMS_SECRET_KEY` | The secret manager | Rotating it signs everyone out; **losing it is survivable** |
| The TOTP encryption key | The secret manager | **Losing it means every user must re-enrol their authenticator.** Back it up separately from the database, and never in the same place |

A database backup without the matching file store is incomplete: an auditor asking to
see the signed letter behind a payment needs both.

## Schedule

| | Frequency | Keep | Where |
| --- | --- | --- | --- |
| Full database dump | Nightly | 35 days hot | Primary backup store |
| WAL archive (point-in-time recovery) | Continuous | 35 days | Primary backup store |
| Full database dump | Monthly | **7 years** | Off-site, write-once if available |
| File store snapshot | Nightly, incremental | 35 days | Primary backup store |
| File store snapshot | Monthly, full | **7 years** | Off-site |
| Secrets | On change | Current plus two previous | Secret manager, separate from the backups |

Encrypt every backup at rest, and restrict who can read them to the same people who may
read client data — a backup is a complete copy of every client's position.

## Taking a backup

```bash
# Database: custom format, so a selective restore is possible later
docker compose exec -T postgres pg_dump -U fms -d fms -Fc \
  > "backup/fms-$(date +%Y%m%d-%H%M).dump"

# File store
docker compose run --rm -v "$PWD/backup:/backup" api \
  tar czf "/backup/files-$(date +%Y%m%d-%H%M).tar.gz" -C /app/var files

# Record what the backup contains, so a restore can be verified against it
docker compose exec -T postgres psql -U fms -d fms -At -c \
  "SELECT 'entries=' || count(*) FROM journal_entries;
   SELECT 'lines=' || count(*) FROM journal_lines;
   SELECT 'audit=' || count(*) FROM audit_log;
   SELECT 'max_entry_date=' || max(entry_date) FROM journal_entries;" \
  > "backup/fms-$(date +%Y%m%d-%H%M).manifest"
```

Keep the manifest with the dump. It is how you tell a good restore from a silent one.

## The restore drill — quarterly, and before go-live

Restore into a **separate** environment. Never practise on production.

```bash
# 1. A clean target
createdb -U fms fms_restore_test

# 2. Restore
pg_restore -U fms -d fms_restore_test --no-owner --clean --if-exists \
  backup/fms-YYYYMMDD-HHMM.dump

# 3. The file store
mkdir -p /tmp/restore && tar xzf backup/files-YYYYMMDD-HHMM.tar.gz -C /tmp/restore
```

Then verify — and these are the checks that actually prove it:

```bash
cd backend
export FMS_DATABASE_URL='postgresql+psycopg://fms:fms@localhost:5432/fms_restore_test'
export FMS_FILE_STORE_PATH=/tmp/restore/files
export FMS_SECRET_KEY='<the key from the secret manager>'

# The schema is at the revision the code expects
alembic current

# The row counts match the manifest
psql -U fms -d fms_restore_test -c \
  "SELECT count(*) FROM journal_entries;
   SELECT count(*) FROM journal_lines;
   SELECT count(*) FROM audit_log;"
```

Restore checklist:

- [ ] `alembic current` is the expected revision, and `alembic upgrade head` is a no-op.
- [ ] Row counts and the latest entry date match the manifest.
- [ ] **The append-only triggers exist.** `pg_dump` does restore them, but check:
      `\dft fms_append_only` and `SELECT tgname FROM pg_trigger WHERE tgname LIKE '%append_only%'`
      should list one per protected table. Then prove it: an `UPDATE journal_entries`
      must fail with "append-only". If the triggers are missing, the restored database
      is **not** the system of record — reinstall them before anyone uses it.
- [ ] Start the API against the restored database. The **trial balance balances**, and
      **every client statement has A = B**. These two are the real test: they exercise
      every balance in the book.
- [ ] A signed letter scan opens from the restored file store, and its SHA-256 matches
      the hash on its instruction. This is what proves the file store and the database
      were restored from the same moment.
- [ ] A reconciliation run for the last closed period reproduces the same breaks it
      found originally — a different answer means something did not come back.
- [ ] Record the restore time. That is your recovery time objective; if it is longer
      than the business will accept, fix it before you need it.

Drop the test database afterwards. It is a full copy of every client's position.

## Point-in-time recovery

With WAL archiving, recovery to a moment — the instant before a bad batch was posted,
say — is possible. Two cautions:

1. **Recovery is not the usual remedy for a wrong posting.** The ledger is append-only
   on purpose: a mistake is corrected by a reversal plus a correct entry, which leaves
   the trail an auditor needs. Point-in-time recovery erases that trail and anything
   else posted since. Use it for corruption or destruction, not for a mistake.
2. **The file store does not roll back with the database.** Recover the database to a
   moment and the file store will hold files whose rows no longer exist. Harmless —
   orphaned blobs are never served — but note it, and restore the matching file-store
   snapshot where it matters.

## Retention and disposal

- **Seven years minimum** from the end of the relationship, for every business record:
  journal, audit log, instructions, letters, signed scans, statements, migration CSVs.
- **No hard deletes.** A user who leaves is disabled, not removed; reference data is
  deactivated. Their name stays on every instruction they signed, which is the point.
- Disposal after seven years is a **compliance decision**, taken in writing against a
  specific retention schedule, and recorded. Do not delete anything to save storage.
- A data subject's erasure request under the DPA does **not** override the regulatory
  retention obligation. Route it to the data protection officer; do not act on it in
  this system.

## Before go-live

- [ ] Backups are running, and have been seen to run on consecutive nights.
- [ ] The restore drill has been completed end to end, with the checklist above signed.
- [ ] The recovery time objective is measured and accepted by the business.
- [ ] `FMS_SECRET_KEY` and the TOTP key are in the secret manager, backed up separately
      from the database, and a named person knows how to retrieve them.
- [ ] Off-site monthly copies are going somewhere that survives the loss of the primary
      environment.

# Audit trail

Kortex records who did what, from where. The log is append-only in a way you
can check, exports in a shape a SIEM already parses, and can be verified by
someone who does not trust the database it came from.

## What is recorded

Five categories. Not everything — a log that records every read is a log nobody
reads, and the noise buries the events that matter.

| Category | Actions |
|---|---|
| Authentication | `auth.login`, `auth.login_failed`, `auth.logout` |
| Authorisation | `member.invited`, `member.granted`, `member.revoked` |
| Credentials | `api_key.created`, `api_key.revoked` |
| Data egress | `scope.exported`, `scope.imported` |
| Destructive & governance | `memory.deleted`, `memory.review.approved`, `memory.review.rejected`, `project.review_mode_changed`, `audit.purged` |

Ordinary reads and writes are deliberately absent. `memories.access_count` and
the memory rows themselves already say what was stored and what was read.

Two things that are **never** written, and one that is:

- **No credential material.** A failed login records that it failed, not the
  password, not a hash of it, not its length. A failed-login log that captures
  credentials is a credential store with a misleading name.
- **No cross-tenant noise.** A failed login for an email that belongs to no
  user is not recorded, because there is no org whose log it could honestly go
  in. Those show up in the application log and to the rate limiter.
- **The caller's IP and user agent** are captured automatically for anything
  that arrives over HTTP.

## Reading it

Requires an org **owner or admin** role. The log is a record of colleagues'
activity and, in most jurisdictions, personal data.

```bash
curl -H "X-API-Key: $KORTEX_API_KEY" \
  "$KORTEX_API/v1/audit/export?since=2026-08-01T00:00:00Z" \
  -o kortex-audit.jsonl
```

Newline-delimited JSON, oldest first, streamed. Field names follow Elastic
Common Schema where one exists — `@timestamp`, `event.action`, `user.id`,
`source.ip` — so a Splunk or Elastic pipeline ingests it without a custom
parser. A custom parser is the step at which a SIEM integration quietly never
gets finished.

```json
{"@timestamp":"2026-08-26T09:14:02+00:00","event":{"action":"api_key.created","id":41,"kind":"event","dataset":"kortex.audit"},"organization":{"id":7},"user":{"id":3,"type":"user"},"target":{"type":"api_key","id":12},"source":{"ip":"10.2.0.44"},"user_agent":{"original":"curl/8.4.0"},"kortex":{"metadata":{"name":"ci","prefix":"kx_a1b2"},"entry_hash":"9f2c…","prev_hash":"41ab…"}}
```

Export is paged by id internally, so an append during a long export cannot
shift a page boundary and skip an entry.

## Proving it was not edited

Two independent mechanisms, because they fail in different ways.

**Prevention** — a database trigger refuses `UPDATE` outright and refuses
`DELETE` unless the session opted in for retention. That stops the accident: a
stray `DELETE FROM audit_log`, an ORM cascade, a migration with a typo. Those
are what actually destroy audit trails in practice. It does not stop a
superuser, who can drop the trigger.

**Detection** — every entry carries a SHA-256 digest of its own content and the
previous entry's digest, per org. Edit a row and its digest stops matching;
remove one from the middle and the next entry's `prev_hash` points at nothing.
Both are visible to whoever verifies, including when the person who tampered
had full database rights.

```bash
curl -H "X-API-Key: $KORTEX_API_KEY" "$KORTEX_API/v1/audit/verify"
```

```json
{"org_id":7,"entries":1482,"unchained":0,"intact":true,
 "summary":"1482 entries verified","head":"9f2c8ab1…"}
```

### Record the head somewhere else

**This is the part that matters, and it is your job, not the software's.**

Verifying a chain against itself proves the entries are consistent with each
other. It cannot prove that none were removed from the *end* — someone who
deletes the last fifty entries leaves a chain that verifies perfectly.

Record `head` somewhere the database's operator does not control: a ticket, a
signed commit, a different cloud account, an email to yourself. Then a later
`verify` whose history no longer reaches that head is evidence, not a hunch.

The export carries `entry_hash` and `prev_hash` on every line for the same
reason: a downstream copy can be verified independently of the database it came
from, which is the only kind of verification that means anything to someone
auditing the database's owner.

## Retention

Off by default.

```bash
KORTEX_AUDIT_RETENTION_DAYS=365
```

A daily worker task deletes entries older than the window, per org, and writes
an `audit.purged` entry recording how many went. A log that can be trimmed
without saying so is not a log.

Deleting a customer's compliance evidence because a default said so is not a
mistake anyone should be able to make by not reading the settings — hence `0`.

Verification anchors on the **earliest surviving entry**, not on the beginning
of time, so a legitimate purge does not report as tampering. `summary` says
"earlier entries purged" and `anchor_prev` shows what the surviving head chains
back to, so the gap is visible rather than hidden. Deleting from the middle or
the end still breaks the chain, which is the case it exists for.

## What this does not give you

Stated plainly, because a compliance claim that overreaches is worse than one
that does not exist:

- **It is not a SIEM.** There is no push integration, no alerting, no
  retention-policy engine. It is an export a SIEM can ingest on a schedule you
  set up.
- **Entries written before the chain existed are unchained.** They are reported
  as such rather than backfilled with digests that would assert a guarantee
  that did not exist at the time.
- **A purge of the oldest entries by someone not entitled to make one is not
  detectable from the chain alone.** The `audit.purged` entry and an externally
  recorded head are what cover it.
- **SOC 2 is a programme, not a feature.** This produces evidence an auditor
  will ask for. It does not produce a report.

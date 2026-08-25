# Runbooks

## KortexApiHighErrorRate

**Symptom:** 5xx error rate > 2% over 10 minutes.

**First steps:**
1. `kubectl -n kortex logs deploy/kortex-api --tail=200 | grep ERROR`
2. Check Postgres availability — most 5xx are DB pool exhaustion or migration drift.
3. Inspect rate-limit middleware — if it's returning 5xx instead of 429, restart Redis (`kubectl -n kortex rollout restart deploy/kortex-api`).

## KortexRecallSlow

**Symptom:** Recall p99 > 1.2s for >10 min.

**First steps:**
1. Check Grafana → Retrieval Performance dashboard → phase breakdown panel.
2. If `plan` p95 is the culprit: planner LLM provider latency. Consider toggling `KORTEX_AGENTIC_RETRIEVAL=false` to fall back to hybrid only.
3. If `rerank` p95: confirm `BgeReranker` model is loaded; HeuristicReranker fallback is correct but much less precise.
4. If `execute`: check `kortex_db_pool_in_use` — likely a Postgres slowdown.

## KortexEmbedBacklog

**Symptom:** `redis_queue_depth{queue="embed"} > 500`.

**First steps:**
1. Scale `worker` deployment: `kubectl -n kortex scale deploy/kortex-worker --replicas=8`.
2. If embeddings are externally hosted (OpenAI/Voyage/Cohere), check provider status.
3. As a one-shot, kick `kortex admin reindex-embeddings` only if you intend a full re-embed; otherwise let `embed_pending` drain naturally.

## KortexCrossOrgViolation

**Symptom:** Cross-org leak attempt observed.

**Action:**
1. Pull the offending request from logs via `kortex_principal_id` + `request_id`.
2. Audit the API key's scope_id with `kortex key show <prefix>`.
3. Revoke the key and re-mint scoped correctly.
4. Run `python -m tools.ruff_plugins.tenant_check packages/` to confirm no raw `select(<TenantModel>)` snuck in.

## Postgres pool exhaustion

**Symptom:** `kortex_db_pool_in_use` stuck at `db_pool_size`.

**First steps:**
1. Check for long-running transactions: `SELECT pid, state, query, query_start FROM pg_stat_activity WHERE state != 'idle' ORDER BY query_start LIMIT 20;`
2. Likely culprit: a stuck `consolidate_tier` task. Kill the worker pod owning it.
3. Bump `db_pool_size` only after confirming the leak isn't a code bug.

## Memories accepted but not searchable

**Alert:** `KortexEmbedFailures` (`kortex_embed_failed > 0`) or `KortexEmbedStalled`
(`kortex_embed_oldest_pending_seconds > 900`).

**Why it matters:** these memories returned 201 from `POST /v1/memories`. The user believes
they were stored. They are not in vector search, and nothing will retry them.

### Triage

```bash
kortex doctor                  # end-to-end: write → embed → search → delete
kortex admin ingest-status     # counts + the most recent failures with their errors
```

`ingest-status` reports:

| Field | Meaning |
|---|---|
| `ok` | Embedded with the currently configured model — searchable. |
| `pending` | Queued or inside a retry backoff window. Normal in small numbers. |
| `failed` | Parked after `max_attempts`. **Not searchable, not being retried.** |
| `oldest_pending_seconds` | If this climbs, the worker is not draining the queue. |

### Common causes

| Symptom | Cause | Fix |
|---|---|---|
| `failed` climbing, error mentions auth/quota | Embedding provider credentials or rate limit | Fix the credential/limit, then requeue |
| `failed` on a few specific memories | Unembeddable input (encoding, size) | Inspect via `ingest-status`; edit or delete those memories |
| `pending` climbing, `failed` zero | Worker or beat pod down, or the model is still downloading | `kubectl get pods -l app=kortex-worker`; check `embedder_unavailable` in the logs |
| Everything pending after a config change | `embedder_model` changed — every vector is stale | Expected; the queue drains on its own |

### Recovery

```bash
kortex admin retry-embeddings            # release parked memories (all orgs)
kortex admin retry-embeddings --org-id 7 # or just one tenant
```

This resets attempts and clears the parked flag; `embed_pending` picks them up on the next
tick. It does **not** touch successful vectors — that is `reindex-embeddings`, which clears
every embedding and re-embeds the entire corpus.

Confirm with `kortex doctor` before closing the incident.

## The review queue is not empty

Memories in the queue are **stored but invisible to recall**. An agent asking
about something held here will be told nothing is known about it.

```bash
curl -s "$KORTEX_API_URL/v1/review" -H "X-API-Key: $KORTEX_API_KEY" | jq '.total'
```

Or open `/app/review` in the console, which shows each held memory with why it
was held and what it resembles among already-approved memories.

### Why something is there

| `review_reason` | Meaning | Usually |
|---|---|---|
| `override_instructions`, `role_reassignment`, `system_prompt_probe`, `exfiltration`, `concealment` | Low-trust content matched a prompt-injection heuristic | A fetched page or tool output containing text aimed at the model |
| `project reviews every write` | The project's `review_mode` is `all` | Deliberate |
| `confidence N below the M threshold` | `review_mode` is `low_confidence` and the writer said it was unsure | Deliberate |

### Clearing it

Approve or reject per item, or in batches of explicit ids. There is no
"approve everything" — clearing a queue you have not read is the failure mode
review exists to prevent.

Rejected memories are kept, not deleted: what an agent tried to store and why
it was refused is the evidence worth having after a poisoning attempt.

Every decision writes an audit row (`memory.review.approved` /
`memory.review.rejected`) recording who made it.

### Turning gating off

```bash
curl -X PATCH "$KORTEX_API_URL/v1/projects/$PROJECT_ID/review-mode" \
  -H "X-API-Key: $KORTEX_API_KEY" -H 'content-type: application/json' \
  -d '{"review_mode": "off"}'
```

This stops *quality* gating only. Suspicious low-trust content is still held —
that is a security control and does not follow the project's preference. Use
`KORTEX_INJECTION_QUARANTINE=false` to disable that too, and understand what
you are turning off first.

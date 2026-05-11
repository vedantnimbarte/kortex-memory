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

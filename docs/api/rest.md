# REST API

The OpenAPI 3 spec is served at `/openapi.json` from a running API instance.
A pre-rendered snapshot lives at `docs/api/openapi.json` and the Postman
collection at `docs/api/postman.json` (importable into Postman / Insomnia).

## Auth

Three header forms work:

```http
X-API-Key: kx_<prefix>_<secret>
# or
Authorization: Bearer kx_<prefix>_<secret>
# or (user / dashboard JWT)
Authorization: Bearer <jwt>
```

## Surfaces

- `/v1/auth/*` — login (returns JWT)
- `/v1/orgs`, `/v1/workspaces`, `/v1/projects`, `/v1/users`, `/v1/api_keys` — tenancy
- `/v1/sessions`, `/v1/conversations`, `/v1/messages`
- `/v1/memories` — CRUD + `/pin` + `/links`
- `/v1/attachments` — `/presign`, `/{id}/finalize`, `/search`
- `/v1/search` — plain hybrid; `/v1/search/recall` — agentic with optional synthesis
- `/v1/ingest/sessions/{id}/messages`, `/v1/ingest/git-log`
- `/v1/export`, `/v1/export/import`
- `/v1/admin/*` — superuser-only

## Idempotency

POSTs accept `Idempotency-Key: <uuid>`. The response (status + body) is cached
for 24h and replayed on retry. Successful 2xx responses replay with header
`Idempotent-Replay: true`.

## ETags

Memory GET responses include a weak ETag derived from `updated_at`. PATCH
accepts `If-Match`; mismatch returns 412.

## Rate limits

Default per-key buckets: 600 read/min, 120 write/min, 30 recall/min. 429
responses include `Retry-After`.

## Write-path status

`POST /v1/memories` returns 201 as soon as the memory is durably stored, but embedding happens
asynchronously — until it completes the memory is not in vector search. `MemoryOut` therefore
carries `embedding_state`:

| Value | Meaning |
|---|---|
| `pending` | Queued or waiting out a retry backoff. |
| `ok` | Embedded with the current model; searchable. |
| `failed` | Retries exhausted. `embed_error` says why. Not searchable, not being retried. |

`GET /v1/admin/ingest-status` aggregates this across the caller's org (all orgs for a
superuser) and lists recent failures. `POST /v1/admin/retry_embeddings` (superuser) requeues
parked memories. See the [runbook](../operators/runbooks.md) for triage.

## Recall budgets

`POST /v1/search/recall` accepts `latency_budget_ms` and `token_budget`
(both default 0 = unlimited). A budget too small for an LLM planner round trip
degrades to plain hybrid retrieval instead of overshooting; `plan_rationale`
records the reason.

The response carries a `usage` object with `mode`, `tokens_in`/`tokens_out`,
`llm_calls`, `plan_steps`, `hops`, `latency_ms`, `cost_usd` and
`budget_exhausted`. `cost_usd` is null unless `KORTEX_LLM_PRICES` is
configured — null means unpriced, not free.

See the [MCP docs](mcp.md#budgets-and-cost-on-recall) for the full shape.

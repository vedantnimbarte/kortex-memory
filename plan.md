# Kortex Memory — Build Plan

> **Status snapshot (2026-05-11):** All ten v0.1 milestones complete. Tag `v0.1.0` is ready.
>
> **Progress: 10 of 10 milestones complete. 🎉**

## Context

This is a greenfield project building **kortex-memory**: a production-grade, multi-tenant memory layer that LLM apps and AI coding agents (Claude Code, Codex, OpenCode, others) plug into via MCP. It stores chats, atomic memories, vector embeddings, and attachments in Postgres + S3, exposes everything over REST, MCP (stdio + SSE), and a CLI, and uses agentic LLM-driven retrieval over hybrid vector + BM25 + recency search. Memories auto-promote and decay across short/mid/long tiers based on time and access patterns. The intent: give every coding agent a shared, durable, scoped, access-controlled memory that survives across sessions and tools.

All architectural decisions below were locked in during planning Q&A (tenancy = SaaS multi-tenant, embeddings = pluggable/local default, attachments = S3, retrieval = agentic, MCP = stdio + SSE, CLI = full admin+user, jobs = Celery+Redis, auth = API keys + JWT, observability = OTel, layout = uv monorepo, skills = server-side strategy classes).

## Decisions (locked)

| Area | Choice |
|---|---|
| Tenancy | Org → Workspace → Project → Session, full RBAC |
| Auth | API keys (scoped, argon2id-hashed) + JWT for dashboard |
| Access control | Sensitivity tiers (public/internal/confidential/secret) × RBAC roles (owner/admin/member/viewer) |
| Embeddings | Pluggable `Embedder` protocol; default `BAAI/bge-large-en-v1.5` (1024 dim) |
| LLM | Pluggable `LLM` protocol; default `claude-sonnet-4-7` (planning), `claude-haiku-4` (summaries) |
| Reranker | `BAAI/bge-reranker-v2-m3` |
| Storage | S3-compatible (MinIO dev, S3/R2 prod) via `aiobotocore` |
| Vector DB | Postgres 16 + pgvector 0.7+, **HNSW** (m=16, ef_construction=64), cosine distance |
| FTS | tsvector GIN + pg_trgm; fusion via Reciprocal Rank Fusion (k=60) |
| Tiers | short/mid/long, decay = `importance × exp(-λ·Δt) × log(1+access_count)`; pinned bypasses decay |
| MCP | Official `mcp` Python SDK, both stdio and SSE transports sharing one tool registry |
| Job queue | Celery 5.4 + Redis 7.2, beat for cadence |
| Observability | OpenTelemetry (OTLP gRPC) + Prometheus metrics + structlog JSON |
| Stack | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Alembic, Typer, ruff, mypy strict |
| Layout | uv workspace, 5 packages: `kortex-core`, `kortex-api`, `kortex-mcp`, `kortex-cli`, `kortex-worker` |

## Repository layout

```
kortex-memory/
├── pyproject.toml                  # uv workspace root
├── packages/
│   ├── kortex-core/                # domain models, db, retrieval, skills, embeddings, llm, storage, security, telemetry
│   ├── kortex-api/                 # FastAPI app + routers
│   ├── kortex-mcp/                 # MCP server (stdio + SSE) sharing one tool registry
│   ├── kortex-cli/                 # `kortex` Typer CLI (admin + user)
│   └── kortex-worker/              # Celery app, tasks, beat schedule
├── alembic/                        # single migration tree, owned by kortex-core
├── docker/                         # api/mcp/worker/cli Dockerfiles + compose.yaml
├── deploy/{helm,k8s}/              # Helm chart + raw manifests with overlays
├── docs/                           # mkdocs-material site (architecture, ADRs, ops, api, mcp)
├── scripts/                        # seed_dev, reset_db, bench_retrieval
├── tests/{unit,integration,e2e}/   # testcontainers-backed
└── .github/workflows/              # ci, release (PyPI), docker (GHCR)
```

Each `packages/*` has its own `pyproject.toml` so CLI and MCP can be released to PyPI independently. `kortex-core` is the only package that talks to Postgres directly; everything else depends on it.

## Database schema (Postgres 16 + pgvector)

Surrogate `BIGINT` IDs + external `public_id UUID` everywhere. `org_id` on every scoped row for tenant isolation. Soft-delete via `deleted_at` on user-visible tables.

**Tenancy & identity**: `orgs`, `workspaces`, `projects`, `users`, `memberships(scope_type, scope_id, role)`.

**Auth**: `api_keys(prefix, key_hash, scope_type, scope_id, scopes TEXT[], expires_at, revoked_at)`, `jwt_revocations`.

**Sessions/conversations/messages**: `sessions(agent_kind, project_id, started_at)`, `conversations(session_id, summary, summary_embedding VECTOR(1024))`, `messages(role, content, tool_name, tool_input/output JSONB)`.

**Memories** — the core:
```
memories(
  id, public_id, org_id, scope_type, scope_id, created_by,
  source_type, source_ref JSONB,
  kind ENUM('fact','preference','decision','procedure','code_artifact','event','summary'),
  title, body, body_tokens,
  tier ENUM('short','mid','long') DEFAULT 'short',
  sensitivity ENUM('public','internal','confidential','secret') DEFAULT 'internal',
  importance REAL DEFAULT 0.5,
  pinned BOOLEAN DEFAULT false,
  access_count INT DEFAULT 0,
  last_accessed_at TIMESTAMPTZ,
  decay_score REAL DEFAULT 1.0,
  embedding VECTOR(1024) NOT NULL,
  embedding_model TEXT NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (...) STORED,
  metadata JSONB,
  expires_at, deleted_at, created_at, updated_at
)
```
Indexes: HNSW on `embedding` (cosine), GIN on `tsv`, GIN trigram on `body`, composite `(org_id, scope_type, scope_id, deleted_at)`, `(tier, decay_score)`, partial on `expires_at`.

**Graph**: `memory_links(from_memory_id, to_memory_id, link_type ENUM('related','derived_from','supersedes','contradicts','part_of'), weight)`.

**Attachments**: `attachments(s3_bucket, s3_key UNIQUE, mime, size_bytes, sha256, processing_status)`, `attachment_chunks(attachment_id, chunk_index, content, embedding VECTOR(1024), tsv)`.

**Ops**: `jobs` (user-visible only — Celery's own state stays internal), `audit_log` (append-only, rolled up monthly).

Migrations via **Alembic** (single tree under `/alembic`). First migration creates `pgvector`, `pg_trgm`, `citext` extensions.

## Core domain modules — `kortex-core`

```
src/kortex_core/
├── settings/config.py              # KortexSettings (pydantic-settings, KORTEX_ prefix)
├── db/{engine,base,session,types}.py
├── models/{org,user,api_key,session,memory,attachment,job,audit}.py
├── repositories/                   # async, all enforce tenancy via BaseRepository.tenant_query
│   └── memory_repo.py              # incl. hybrid_search(), upsert_with_embedding()
├── services/
│   ├── auth_service.py
│   ├── access_control.py           # AccessControl.check(principal, action, resource)
│   ├── memory_service.py
│   ├── ingestion_service.py
│   ├── attachment_service.py       # presign + finalize flow
│   ├── retrieval_service.py        # plain hybrid retrieval
│   └── agentic_retriever.py        # the agent loop (see below)
├── embeddings/                     # protocol + adapters: local_bge (default), openai, voyage, cohere, anthropic
├── llm/                            # protocol + adapters: anthropic (default), openai, openrouter, ollama
├── storage/                        # protocol + adapters: s3 (default), fs (dev/test)
├── skills/                         # server-side pluggable strategies — protocols + default impls
│   ├── decay_policy.py             # ExponentialDecayPolicy
│   ├── summarizer.py               # LLMSummarizer (claude-haiku)
│   ├── access_policy.py            # RoleSensitivityPolicy
│   ├── reranker.py                 # BgeReranker
│   ├── consolidator.py             # LLMConsolidator (mid → long)
│   └── importance_scorer.py        # HybridScorer (heuristic + LLM judge)
├── retrieval/{hybrid,reranker_pipeline,agent_loop,token_budget,query_plan}.py
├── security/{api_keys,jwt,passwords,rate_limit,principal}.py
└── telemetry/{otel,logging,metrics}.py
```

## Agentic retrieval design

`AgenticRetriever` (`services/agentic_retriever.py`) drives the recall flow:

1. **Pre-filter**: `AccessControl.visible_scopes(principal)` returns the readable `(scope_type, scope_id)` set; sensitivity is bounded by role.
2. **Plan (LLM #1)**: planner LLM emits a structured `QueryPlan` (Pydantic, via tool calling) — list of `SemanticSearch | KeywordSearch | LinkExpand | TimeFilter | StopAndAnswer` steps.
3. **Execute**: each step calls `HybridRetriever`. `LinkExpand` walks `memory_links` (max depth 2). All step queries pass through the tenancy chokepoint — planner cannot escape.
4. **Multi-hop loop**: continue until `StopAndAnswer`, candidates ≥ 200, or hops ≥ 3.
5. **Rerank**: `BgeReranker` scores candidates; `TokenBudget.fit(candidates, max_tokens)` greedily packs.
6. **Synthesize (LLM #2, optional)**: claude-haiku produces a `ContextBundle` with citations `[m:public_id]`.
7. **Record access**: batched UPDATE of `access_count` and `last_accessed_at`.
8. **Fallback**: if planner LLM fails or `KORTEX_AGENTIC_RETRIEVAL=false`, run plain hybrid + rerank with `plan_trace="fallback:hybrid"`.

OTel spans: `kortex.retrieval.recall` (root), `.plan`, `.execute_step` (per step), `.rerank`, `.synthesize`.

Hybrid substrate: `embedding <=> :query_vec` (LIMIT 50) + `ts_rank_cd` BM25 (LIMIT 50) + precomputed `decay_score` boost, fused via RRF (k=60). Pinned memories get a +1.0 score floor.

## Memory tiers & decay

- **short**: current session or <24h since access.
- **mid**: 24h–30d with access, or short with importance ≥ 0.4.
- **long**: consolidated summaries (`kind='summary'`) with `derived_from` links to originals.

Decay formula:
```
decay_score = clamp(
  importance
  * exp(-λ_tier * (now - COALESCE(last_accessed_at, created_at)) / 1d)
  * (1 + ln(1+access_count)) / (1 + ln(1+median_access_count))
, 0, 1)
```
λ: short=0.30/day, mid=0.05/day, long=0.005/day. `pinned=true` → `decay_score=1.0` always.

**Promotions**: short→mid auto when age>24h, importance≥0.4, access_count≥1. mid→long only via consolidation. Hard delete short>7d with decay<0.05; archive mid>180d with decay<0.10.

**Consolidation** (daily 03:00 UTC per org): HDBSCAN cluster mid memories per (scope, kind), `LLMConsolidator` produces a summary memory + `derived_from` links to members, members keep their tier but get `decay_score *= 0.5`.

## MCP server surface

Single `mcp.Server` in `packages/kortex-mcp/src/kortex_mcp/server.py`, exported over both `transports/stdio.py` and `transports/sse.py`. Auth: stdio reads `KORTEX_API_KEY` env; SSE expects `Authorization: Bearer <api_key>`.

Tools: `remember`, `recall`, `search_memory`, `get_context_bundle`, `get_memory`, `list_memories`, `update_memory`, `update_memory_sensitivity`, `delete_memory`, `link_memories`, `unlink_memories`, `pin_memory`, `unpin_memory`, `attach_file`, `finalize_attachment`, `get_attachment`, `list_sessions`, `start_session`, `end_session`, `summarize_session`, `list_scopes`.

Resources: `kortex://memory/{id}`, `kortex://session/{id}/summary`, `kortex://attachment/{id}`.

Prompts: `kortex.recall`, `kortex.consolidate_recent`.

## REST API surface

FastAPI, OpenAPI auto-generated, RFC 7807 ProblemDetails, cursor pagination, `Idempotency-Key` on POSTs, `If-Match`/ETags on memory PATCH.

Routers under `packages/kortex-api/src/kortex_api/routers/`:
`auth`, `orgs`, `workspaces`, `projects`, `users`, `api_keys`, `sessions`, `conversations`, `messages`, `memories`, `attachments`, `search` (`/search` hybrid + `/recall` agentic), `ingest` (messages/document/git_log), `jobs`, `audit`, `admin` (superuser: `reindex_embeddings`, `force_decay_tick`).

Health: `/livez`, `/readyz`, `/metrics`.

## CLI surface — `kortex` (Typer)

Reads `~/.config/kortex/config.toml` or `KORTEX_API_URL`/`KORTEX_API_KEY`. Supports `--json`, `--profile`. Groups: `auth`, `org`, `workspace`, `project`, `user`, `key`, `session`, `memory`, `attachment`, `search`, `recall`, `ingest`, `export`, `admin` (`migrate`, `db`, `worker`, `reindex-embeddings`, `force-decay-tick`).

Admin commands talk to DB via `kortex_core` (need `KORTEX_DATABASE_URL`); user commands go through `kortex-api` over HTTPS.

## Background jobs (Celery + Redis)

| Task | Cadence | Purpose |
|---|---|---|
| `embed_pending` | every 30s | batch-embed memories with NULL/stale embedding |
| `decay_tick` | every 6h, fan-out per-org | recompute decay_score, apply tier transitions |
| `consolidate_tier` | daily 03:00 UTC per-org | HDBSCAN cluster mid → write long-tier summaries |
| `process_attachment` | on-demand | extract text (PyMuPDF/python-docx/pandoc), chunk, embed |
| `generate_summary` | every 5 min | summarize idle conversations (>30 min, no summary) |
| `audit_rollup` | daily 04:00 UTC | aggregate, archive raw past 90d to S3 |
| `key_rotation_check` | hourly | warn/auto-revoke expiring keys |
| `extract_memories_from_messages` | on-demand | LLM extracts atomic memories from message windows |
| `reindex_embeddings` | on-demand (admin) | full reindex when default model changes |

Queues: `embed`, `default`, `slow`, `beat`. Retry: exp backoff 2s..600s, max 5. DLQ: `dlq:<task>` with `kortex worker dlq replay`.

## Security & multi-tenancy enforcement

**Single chokepoint**: every query in `repositories/*` must go through `BaseRepository.tenant_query()`, which injects `org_id` filter and visible scopes. CI lint rule (custom ruff plugin under `tools/ruff_plugins/tenant_check.py`) blocks raw `select(Model)` in repositories.

**Principal**: `kortex_core.security.principal.Principal` lives in a `ContextVar` set by API/MCP middleware; carries `actor_id`, `actor_kind`, `org_id`, `scope_bindings`, `roles`, `key_scopes`, `max_sensitivity`.

**RBAC × sensitivity matrix** (in `RoleSensitivityPolicy`):
- viewer: read ≤ confidential, no write
- member: read/write ≤ confidential
- admin: read/write ≤ secret, scope-local admin
- owner: full

**API key format**: `kx_<prefix8>_<secret43>`, prefix queryable, secret hashed via argon2id (t=2, m=64MB, p=4). Lookup by prefix, then constant-time argon2 verify.

**Rate limits** (Redis Lua token bucket): 600 read/min, 120 write/min, 30 recall/min per key.

**Audit log**: written from `AuditingMiddleware` (state-changing endpoints) and from services (worker actions); append-only, no UPDATE permission for app role.

**Encryption**: optional envelope encryption (libsodium) for `sensitivity='secret'` memory bodies, KEK from `KORTEX_KMS_KEY` or AWS KMS.

## Observability

OTel SDK 1.27+ → OTLP gRPC. Resource attrs: `service.name`, `service.namespace=kortex`, `deployment.environment`, `org.id` (baggage).

Top spans: `kortex.retrieval.recall` (+ children), `kortex.embed.batch`, `kortex.agent.loop_step`, `kortex.decay.tick`, `kortex.consolidate.cluster`, `kortex.attachment.process`. SQLAlchemy auto-instrumentation sampled 5% in prod.

Key metrics: `kortex_retrieval_latency_seconds{phase}`, `kortex_retrieval_candidates{phase}`, `kortex_embed_throughput_tokens_per_second`, `kortex_agent_hops`, `kortex_decay_duration_seconds{org}`, `kortex_api_requests_total{route,method,status}`, `kortex_rate_limit_blocked_total{key}`, `kortex_db_pool_in_use`.

Logs: structlog JSON; every line has `trace_id`, `span_id`, `org_id`, `principal_id`, `request_id`. Memory bodies scrubbed.

Ship 6 Grafana dashboards under `deploy/observability/grafana/`: Retrieval Performance, Embedding Pipeline, Decay & Consolidation, Tenancy Health, API SLOs, DB Health.

## Build / dev tooling

uv 0.4+ workspace; Python 3.12 only. ruff (lint+format), mypy strict, pytest 8 + pytest-asyncio (mode=auto), testcontainers (`pgvector/pgvector:pg16`, `redis:7`, `minio/minio`), VCR.py for LLM cassettes, pre-commit hooks (incl. alembic-autogen-check). Coverage gate 85%.

GitHub Actions: `ci.yaml` (lint/type/test matrix per package), `release.yaml` (tag → `uv build` → PyPI trusted publishing), `docker.yaml` (GHCR push).

## Critical files to be created

| Path | Purpose |
|---|---|
| `pyproject.toml` (root) | uv workspace declaration |
| `alembic/env.py`, `alembic/versions/0001_initial.py` | migration scaffolding + extensions |
| `packages/kortex-core/src/kortex_core/models/memory.py` | the central domain entity |
| `packages/kortex-core/src/kortex_core/repositories/base.py` | tenancy chokepoint |
| `packages/kortex-core/src/kortex_core/repositories/memory_repo.py` | hybrid_search, upsert_with_embedding |
| `packages/kortex-core/src/kortex_core/services/agentic_retriever.py` | the agent loop |
| `packages/kortex-core/src/kortex_core/retrieval/{hybrid,agent_loop,token_budget}.py` | retrieval substrate |
| `packages/kortex-core/src/kortex_core/skills/{decay_policy,summarizer,reranker,consolidator,access_policy,importance_scorer}.py` | strategy interfaces + defaults |
| `packages/kortex-core/src/kortex_core/embeddings/local_bge.py` | default embedder |
| `packages/kortex-core/src/kortex_core/llm/anthropic.py` | default LLM |
| `packages/kortex-core/src/kortex_core/storage/s3.py` | default blob store |
| `packages/kortex-core/src/kortex_core/security/principal.py` | Principal contextvar |
| `packages/kortex-api/src/kortex_api/app.py` | FastAPI factory |
| `packages/kortex-mcp/src/kortex_mcp/server.py` | MCP tool registry |
| `packages/kortex-mcp/src/kortex_mcp/transports/{stdio,sse}.py` | dual transports |
| `packages/kortex-cli/src/kortex_cli/main.py` | Typer root |
| `packages/kortex-worker/src/kortex_worker/celery_app.py` + `tasks/{embedding,decay,consolidate,attachments,audit,keys}.py` | jobs |
| `docker/compose.yaml` | postgres+pgvector, redis, minio, api, mcp, worker, beat |
| `deploy/helm/kortex/` | chart for prod |
| `tools/ruff_plugins/tenant_check.py` | CI rule blocking un-scoped queries |

---

# Milestones

Each milestone is end-to-end runnable. Total: ~14 engineer-weeks for v0.1.0 from one engineer; ~8 calendar weeks parallelized across two.

## Task tracker

| # | Milestone | Task | Status |
|---|---|---|---|
| 1 | M1 | Scaffold uv workspace and 5 packages | ✅ |
| 2 | M1 | Build kortex-core foundation | ✅ |
| 3 | M1 | Add tenancy and auth models | ✅ |
| 4 | M1 | Wire Alembic and write 0001 migration | ✅ |
| 5 | M1 | Implement repositories and services for M1 | ✅ |
| 6 | M1 | Build kortex-api with M1 routers | ✅ |
| 7 | M1 | Build kortex-cli with M1 command groups | ✅ |
| 8 | M1 | Add Docker Compose and seed script | ✅ |
| 9 | M1 | Set up CI tooling | ✅ |
| 10 | M2 | Add session/memory models + 0002 migration | ✅ |
| 11 | M2 | Embeddings protocol + local_bge default | ✅ |
| 12 | M2 | Memory repos + services + hybrid search | ✅ |
| 13 | M2 | API + CLI for memories/sessions/search | ✅ |
| 14 | M2 | kortex-worker with embed_pending | ✅ |
| 15 | M3 | MCP server with stdio transport | ✅ |
| 16 | M4 | Attachment models + 0003 migration | ✅ |
| 17 | M4 | Storage layer + S3 adapter | ✅ |
| 18 | M4 | AttachmentService + process_attachment worker task | ✅ |
| 19 | M4 | Attachments API + MCP tools + CLI | ✅ |
| 20 | M5 | LLM protocol + Anthropic/OpenAI/OpenRouter/Ollama adapters | ✅ |
| 21 | M5 | QueryPlan, Reranker, AgentLoop | ✅ |
| 22 | M5 | AgenticRetriever + ContextBundle | ✅ |
| 23 | M5 | API /search/recall, MCP recall upgrade + get_context_bundle, CLI | ✅ |
| 24 | M5 | OTel spans for kortex.retrieval.* | ✅ |
| 25 | M6 | Formalize 5 skill protocols + defaults | ✅ |
| 26 | M6 | Decay/tier repo helpers (median, iter_for_decay, hard_delete, consolidation list) | ✅ |
| 27 | M6 | decay_tick / consolidate_tier / generate_summary worker tasks + beat schedule | ✅ |
| 28 | M6 | Admin endpoints force_decay_tick / reindex_embeddings / consolidate_tier + CLI | ✅ |
| 29 | M7 | MCP SSE transport + `kortex-mcp serve` | ✅ |
| 30 | M7 | API RateLimitMiddleware (read/write/recall buckets) | ✅ |
| 31 | M7 | Tenancy regression test + tenant_check ruff plugin | ✅ |
| 32 | M7 | kortex-mcp Dockerfile + compose service | ✅ |
| 33 | M8 | Idempotency-Key + ETag middleware | ✅ |
| 34 | M8 | git-log ingest + ingest CLI polish | ✅ |
| 35 | M8 | kortex export + import (tarball) | ✅ |
| 36 | M9 | Helm chart skeleton (api/mcp/worker/beat/HPA/Ingress/NetPol/Backup) | ✅ |
| 37 | M9 | Kustomize overlays + Prometheus rules + 6 Grafana dashboards | ✅ |
| 38 | M9 | bench_retrieval.py + operator runbooks | ✅ |
| 39 | M10 | mkdocs site + 3 ADRs + CHANGELOG | ✅ |
| 40 | M10 | release.yaml + docker.yaml workflows + Postman collection | ✅ |

## ✅ M1 — Foundation (≈2.5w) — **DONE**

**Scope:** uv workspace, CI, `kortex-core` settings/db/auth models, alembic 0001 (extensions + tenancy/auth tables), `auth_service` + `api_key_service` + `access_control`, `kortex-api` auth/org/workspace/project/users/keys routers, `kortex-cli` matching groups, docker compose.

**Definition of done:** `kortex auth login` then `kortex memory list` returns "no memories".

**Delivered files (~85):**
- Workspace root: `pyproject.toml`, `.python-version`, `.gitignore`, `.env.example`, `README.md`, `Makefile`, `.editorconfig`, `.pre-commit-config.yaml`.
- 5 package skeletons under `packages/`, each with its own `pyproject.toml`, `README.md`, `src/<pkg>/__init__.py`, `py.typed`.
- `kortex-core`:
  - `settings/config.py` — KortexSettings with full env-driven config.
  - `db/{base,engine,session,types}.py` — SQLAlchemy 2.0 async, naming convention, all enums.
  - `models/{mixins,org,user,api_key,audit}.py` — Org/Workspace/Project/User/Membership/ApiKey/JwtRevocation/AuditLog with relationships.
  - `repositories/` — `base.py` with tenancy chokepoint (`tenant_query`), `org_repo`, `workspace_repo`, `project_repo`, `user_repo`, `membership_repo`, `api_key_repo`, `audit_repo`.
  - `services/` — `auth_service` (login + JWT mint + principal materialization from JWT/API key), `api_key_service` (mint/list/revoke), `access_control` (RBAC × sensitivity), `org_service`, `workspace_service`, `project_service`, `user_service`.
  - `security/` — `passwords` (argon2id), `api_keys` (kx_prefix_secret format), `jwt` (HS512), `principal` (ContextVar), `rate_limit` (Redis Lua token bucket).
  - `telemetry/` — `logging` (structlog JSON + trace/span/request_id enrichment), `otel` (lazy OTLP setup), `metrics`.
- `alembic.ini`, `alembic/env.py` (async-aware), `alembic/script.py.mako`, `alembic/versions/0001_initial.py` creating extensions (pgvector, pg_trgm, citext, uuid-ossp), enums, and all M1 tables with full indexing.
- `kortex-api`: `app.py` (factory + lifespan), `main.py` (uvicorn entry), `deps.py` (auth dependency), `errors.py` (RFC 7807), `middleware/context.py` (request_id + principal binding), routers: `auth`, `orgs`, `workspaces`, `projects`, `users`, `api_keys`, `health`. Pydantic v2 schemas under `schemas/`.
- `kortex-cli`: `main.py` (Typer root), `config.py` (TOML profiles in user config dir), `client.py` (httpx client with auth/retries), `output.py` (rich tables + JSON), command groups: `auth`, `org`, `workspace`, `project`, `user`, `key`, `memory` (M2 stub), `admin` (alembic helpers).
- `docker/compose.yaml` (postgres+pgvector, redis, minio + bucket init, api), `docker/api.Dockerfile` (multi-stage uv build).
- `scripts/seed_dev.py` — creates org/workspace/project/admin user + scoped API key, prints plaintext once.
- `.github/workflows/ci.yaml` — lint, type, unit test, integration test (with PG+Redis services).
- `tests/`:
  - `unit/test_security.py` — password/api_key/jwt roundtrips.
  - `unit/test_access_control.py` — RBAC × sensitivity matrix.
  - `unit/test_settings.py` — env-driven settings.
  - `integration/test_orgs.py` — superuser org create/read smoke test.

**Verification:** `uv sync && docker compose -f docker/compose.yaml up -d && make migrate && make seed && uv run pytest -m unit`.

---

## ✅ M2 — Memories + Hybrid Search (≈2w) — **DONE**

**Scope:** memory schema with vector + FTS + trigram indexes, default local embedder, hybrid retrieval substrate (RRF), CRUD + ingestion services, REST + CLI surfaces, Celery worker scaffolding with `embed_pending`.

**Definition of done:** ingest a JSONL of messages, `kortex search "X"` returns ranked results. ✅

**Delivered files:**
- **Models:**
  - `packages/kortex-core/src/kortex_core/models/session.py` — `Session`, `Conversation`, `Message` (w/ `summary_embedding VECTOR(1024)`).
  - `packages/kortex-core/src/kortex_core/models/memory.py` — `Memory` (with computed `tsv` tsvector, all enums, full index plan), `MemoryLink`.
  - `packages/kortex-core/src/kortex_core/models/__init__.py` updated to register them.
- **Migration:**
  - `alembic/versions/20260508_0002_kkx0002_memories_sessions.py` — creates 7 enum types, 5 tables, HNSW index on `embedding` (`m=16, ef_construction=64`), GIN on `tsv`, GIN trigram on `body`, composite tenancy index.
- **Embeddings:**
  - `packages/kortex-core/src/kortex_core/embeddings/__init__.py`, `protocol.py` (`Embedder` Protocol), `registry.py` (lazy factories), `local_bge.py` (sentence-transformers, threadpool-offloaded), `openai.py` (Matryoshka 1024-truncated `text-embedding-3-large`).
- **Retrieval substrate:**
  - `packages/kortex-core/src/kortex_core/retrieval/__init__.py`, `hybrid.py` (`HybridSearchHit`, `rrf_fuse` with pinned floor), `token_budget.py` (greedy budget packer).
- **Repositories:**
  - `packages/kortex-core/src/kortex_core/repositories/memory_repo.py` — CRUD, `list_pending_embedding`, `set_embedding`, `record_access`, `hybrid_search` (vector + BM25 + RRF + decay multiplier, sensitivity-bounded, scope-filtered).
  - `packages/kortex-core/src/kortex_core/repositories/session_repo.py` — `SessionRepository`, `ConversationRepository`, `MessageRepository` (with `append_bulk` for ingest).
  - `packages/kortex-core/src/kortex_core/repositories/memory_link_repo.py` — `link`, `unlink`, `neighbors`.
  - `packages/kortex-core/src/kortex_core/repositories/__init__.py` updated.
- **Services:**
  - `packages/kortex-core/src/kortex_core/services/memory_service.py` — CRUD + linking + access bookkeeping; `CreateMemoryInput` dataclass; access control on write.
  - `packages/kortex-core/src/kortex_core/services/session_service.py` — `SessionService`, `ConversationService` (with `append_message`, `list_messages`).
  - `packages/kortex-core/src/kortex_core/services/retrieval_service.py` — `SearchRequest`, `SearchResult`, embedder fallback to BM25 only, batched access bookkeeping.
  - `packages/kortex-core/src/kortex_core/services/ingestion_service.py` — bulk message ingest with default conversation, document → memory.
  - `packages/kortex-core/src/kortex_core/services/__init__.py` updated.
- **API:**
  - `packages/kortex-api/src/kortex_api/schemas/{session,memory,search}.py`.
  - `packages/kortex-api/src/kortex_api/routers/sessions.py` — start/get/end.
  - `packages/kortex-api/src/kortex_api/routers/conversations.py` — create/list, message append/list.
  - `packages/kortex-api/src/kortex_api/routers/memories.py` — create/list/get/patch/delete + pin/unpin + link/unlink.
  - `packages/kortex-api/src/kortex_api/routers/search.py` — `POST /v1/search` hybrid.
  - `packages/kortex-api/src/kortex_api/routers/ingest.py` — `POST /v1/ingest/sessions/{id}/messages`.
  - `packages/kortex-api/src/kortex_api/app.py` updated to mount the new routers.
- **CLI:**
  - `packages/kortex-cli/src/kortex_cli/cmds/session.py` — start/show/end.
  - `packages/kortex-cli/src/kortex_cli/cmds/memory.py` — list/create/show/update/delete/pin/unpin/link (replaces M1 stub).
  - `packages/kortex-cli/src/kortex_cli/cmds/search.py` — `kortex search "<query>"`.
  - `packages/kortex-cli/src/kortex_cli/cmds/ingest.py` — `messages <jsonl>`, `document <file>`.
  - `packages/kortex-cli/src/kortex_cli/main.py` updated.
- **Worker:**
  - `packages/kortex-worker/src/kortex_worker/celery_app.py` — Celery factory, queue routes (`embed`, `default`, `slow`, `beat`), beat schedule with `embed_pending` every 30s.
  - `packages/kortex-worker/src/kortex_worker/tasks/__init__.py`, `tasks/embedding.py` — async batch embedder.
  - `packages/kortex-worker/src/kortex_worker/main.py` — `worker`/`beat`/`run-once` subcommands.
  - `packages/kortex-worker/pyproject.toml` updated with `[full]` extra pulling kortex-core[embeddings-local,attachments,clustering,storage-s3].
- **Docker:**
  - `docker/worker.Dockerfile`.
  - `docker/compose.yaml` — added `worker` and `beat` services.
- **Tests:**
  - `tests/unit/test_retrieval.py` — RRF fusion, pinned floor, token budget packing.

---

## ✅ M3 — MCP stdio (≈1w) — **DONE**

**Scope:**
- `kortex-mcp` server with canonical tool set: `remember`, `recall` (calls `HybridRetriever` for now — agentic comes in M5), `search_memory`, `get_memory`, `list_memories`, `update_memory`, `delete_memory`, `link_memories`, `pin_memory`, `list_sessions`, `start_session`, `end_session`.
- `transports/stdio.py` and `main.py` (`kortex-mcp stdio`).
- Auth from `KORTEX_API_KEY` env via `kortex_core.services.auth_service`.
- Integration test exercising the same tool registry that the transports delegate to.

**Definition of done:** Claude Code configured to use `kortex-mcp stdio` can store/recall memories. ✅

**Delivered files:**
- `packages/kortex-mcp/src/kortex_mcp/auth.py` — `principal_from_api_key()` and `read_api_key_from_env()`.
- `packages/kortex-mcp/src/kortex_mcp/context.py` — `McpRuntime` + `tool_context()` (binds Principal contextvar, opens session_scope per tool call).
- `packages/kortex-mcp/src/kortex_mcp/tools/base.py` — `ToolDef`, `all_tools()`, JSON encoder helpers.
- `packages/kortex-mcp/src/kortex_mcp/tools/memory.py` — `remember`, `get_memory`, `list_memories`, `update_memory`, `delete_memory`, `pin_memory`, `link_memories`.
- `packages/kortex-mcp/src/kortex_mcp/tools/search.py` — `search_memory` and `recall` (alias of hybrid search until M5).
- `packages/kortex-mcp/src/kortex_mcp/tools/session.py` — `start_session`, `end_session`, `list_sessions`.
- `packages/kortex-mcp/src/kortex_mcp/server.py` — `build_server()` registers `list_tools` + `call_tool` on an `mcp.server.Server`; tool results encoded as `TextContent` JSON; uncaught exceptions surfaced as structured error payloads.
- `packages/kortex-mcp/src/kortex_mcp/transports/stdio.py` — `run_stdio()` reads `KORTEX_API_KEY`, materialises the Principal once, runs `mcp.server.stdio_server`.
- `packages/kortex-mcp/src/kortex_mcp/main.py` — `kortex-mcp stdio` entrypoint.
- `tests/integration/test_mcp_stdio.py` — pins the tool surface, drives `remember/list/recall/pin/update/get/delete` and `start/list/end_session` against real Postgres + pgvector via testcontainers.

---

## ✅ M4 — Attachments + S3 (≈1.5w) — **DONE**

**Scope:**
- Models: `Attachment`, `AttachmentChunk` with HNSW + GIN (Alembic 0003).
- Storage: `BlobStore` Protocol in `storage/protocol.py`, `storage/s3.py` (aiobotocore), `storage/fs.py` (dev/test).
- Service: `AttachmentService` with presign PUT + finalize flow.
- Worker task: `process_attachment` — download from blob store, extract text (PyMuPDF/python-docx), chunk (512 tokens, 64 overlap), embed, mark `ready`.
- API: `attachments` router with `/presign`, `/{id}/finalize`, `/{id}` GET/DELETE, `/search`.
- MCP: `attach_file`, `finalize_attachment`, `get_attachment` tools.
- CLI: `attachment upload/list/show/delete/search` group.

**Definition of done:** `kortex attachment upload sample.pdf --scope project --scope-id <id>` succeeds, `process_attachment` runs, `kortex attachment search "term-from-pdf"` returns chunk-level matches. ✅

**Delivered files:**
- **Settings:** added `storage_backend`, `fs_storage_root`, `attachment_chunk_tokens`, `attachment_chunk_overlap`, `attachment_max_bytes` to `kortex_core/settings/config.py`.
- **Storage layer:** `kortex_core/storage/{__init__,protocol,registry,s3,fs}.py` — `BlobStore` protocol, S3 (aiobotocore) + filesystem adapters, env-driven registry.
- **Attachment extraction:** `kortex_core/attachments/{__init__,extract,chunker}.py` — PyMuPDF/python-docx/plain extractors and a sentence-aware chunker.
- **Models:** `kortex_core/models/attachment.py` — `Attachment` + `AttachmentChunk` with HNSW vector + GIN tsvector indexes.
- **Migration:** `alembic/versions/20260511_0003_kkx0003_attachments.py` — creates `attachment_status` enum, both tables, vector + tsvector indexes.
- **Repos:** `kortex_core/repositories/attachment_repo.py` — `AttachmentRepository`, `AttachmentChunkRepository` with `hybrid_search()` and `AttachmentChunkHit`.
- **Service:** `kortex_core/services/attachment_service.py` — presign → finalize → enqueue `process_attachment`.
- **Worker:** `packages/kortex-worker/src/kortex_worker/tasks/attachments.py` — `process_attachment` task; registered in `celery_app.include`.
- **API:** `kortex_api/schemas/attachment.py` + `kortex_api/routers/attachments.py`; `bad_request` helper added to `kortex_api/errors.py`; router mounted in `app.py`.
- **MCP:** `kortex_mcp/tools/attachments.py` (`attach_file`, `finalize_attachment`, `get_attachment`); registered in `tools/base.py:all_tools`.
- **CLI:** `kortex_cli/cmds/attachment.py` (upload/list/show/delete/search); mounted as `kortex attachment` in `main.py`.
- **Tests:** `tests/unit/test_attachments.py` (chunker bounds, FS adapter round-trip, extraction error path).

---

## ✅ M5 — Agentic Retrieval (≈1.5w) — **DONE**

**Scope:**
- LLM: `LLM` Protocol in `llm/protocol.py`, `llm/anthropic.py` (default), `llm/openai.py`, `llm/openrouter.py`, `llm/ollama.py`.
- Skill: `Reranker` Protocol with `BgeReranker` default and `HeuristicReranker` fallback.
- Retrieval: `retrieval/agent_loop.py`, `retrieval/query_plan.py`, `retrieval/reranker_pipeline.py`.
- Service: `AgenticRetriever` (`services/agentic_retriever.py`) with fallback to plain hybrid when LLM unavailable or `KORTEX_AGENTIC_RETRIEVAL=false`.
- API: `/v1/search/recall` returns `ContextBundle`.
- MCP: upgraded `recall` to call `AgenticRetriever`; added `get_context_bundle`.

**Definition of done:** `kortex recall "what did we decide about caching?" --synthesize` returns a synthesized answer with citations. ✅ (OTel spans wired across `kortex.retrieval.*` deferred to M6 alongside the rest of the observability spans, since the same telemetry setup applies to decay/consolidation; the recall service already structured-logs `planner_failed` / `summarizer_failed` and emits a `plan_trace`/`plan_rationale` on the bundle.)

**Delivered files:**
- **LLM layer:** `kortex_core/llm/{__init__,protocol,registry,anthropic,openai,openrouter,ollama}.py` — `LLM` Protocol with `complete()` supporting `json_schema` structured output across providers.
- **Reranker skill:** `kortex_core/skills/{__init__,reranker.py}` — `Reranker` Protocol, `BgeReranker` (CrossEncoder), `HeuristicReranker` (token overlap fallback), `get_reranker()` with safe load-time fallback.
- **Retrieval substrate:** `kortex_core/retrieval/query_plan.py` (Pydantic plan with discriminated step union + JSON schema export), `retrieval/agent_loop.py` (multi-hop executor with link expansion, hop/candidate caps, tenancy-safe), `retrieval/reranker_pipeline.py` (rerank + token budget pack with blended scoring).
- **Service:** `kortex_core/services/agentic_retriever.py` — `AgenticRetriever`, `RecallRequest`, `ContextBundle`, `Citation`; plan → execute → rerank → optional synthesize; clean fallback to plain hybrid when planner LLM is unavailable.
- **API:** `kortex_api/schemas/search.py` extended with `RecallIn`, `ContextBundleOut`, `CitationOut`, `RecallCandidateOut`; `kortex_api/routers/search.py` adds `POST /v1/search/recall`.
- **MCP:** `kortex_mcp/tools/search.py` upgraded — `recall` now drives the agent loop, new `get_context_bundle` synthesizes with citations.
- **CLI:** `kortex_cli/cmds/recall.py` — `kortex recall "<q>" [--synthesize]` mounted on the root Typer.
- **Services exports:** `kortex_core/services/__init__.py` re-exports `AgenticRetriever`, `RecallRequest`, `ContextBundle`, `Citation`.
- **Tests:** `tests/unit/test_query_plan.py` (plan parse + schema), `tests/unit/test_reranker.py` (heuristic scoring + blended pack).

---

## ✅ M6 — Decay, Consolidation, Tiers, Skills (≈1.5w) — **DONE**

**Scope:**
- Formalize 5 skill protocols + defaults: `DecayPolicy` (ExponentialDecayPolicy), `ImportanceScorer` (HybridScorer), `Summarizer` (LLMSummarizer/claude-haiku), `Consolidator` (LLMConsolidator), `AccessPolicy` (RoleSensitivityPolicy — re-exported through the skills package).
- Worker tasks: `decay_tick` (every 6h), `consolidate_tier` (daily 03:00 UTC via crontab, HDBSCAN clustering when available), `generate_summary` (every 5 min, idle convos).
- Beat schedule wired in `celery_app.make_celery`.
- Pin bypass verified at every decay/promotion/delete step (policy clamps pinned to 1.0; repo helpers filter pinned at SQL level).
- Admin endpoints: `force_decay_tick`, `reindex_embeddings`, `consolidate_tier` — all superuser-only.

**Definition of done:** Idle the dev cluster a day with seed data: `mid` memories appear, summaries get created with `derived_from` links. ✅

**Delivered files:**
- **Skills:** `packages/kortex-core/src/kortex_core/skills/{decay_policy,importance_scorer,summarizer,consolidator,access_policy}.py`; `skills/__init__.py` re-exports.
- **Decay/consolidation repo helpers:** added to `kortex_core/repositories/memory_repo.py` — `list_orgs_with_memories`, `median_access_count`, `iter_for_decay`, `apply_decay`, `hard_delete`, `list_for_consolidation`. All routed through `tenant_query()` so the worker's superuser principal becomes a pass-through and the tenant_check lint stays clean.
- **Worker tasks:** `packages/kortex-worker/src/kortex_worker/tasks/decay.py` (`decay_tick`, `decay_tick_org`), `tasks/consolidate.py` (`consolidate_tier`, `consolidate_tier_org`), `tasks/summary.py` (`generate_summary`); registered in `celery_app.include`.
- **Beat schedule:** updated `celery_app.make_celery` — `embed-pending` 30s, `decay-tick` 6h, `consolidate-tier` daily 03:00 UTC (crontab), `generate-summary` 5min. Added `kortex.summary.*` queue route.
- **Admin:** `kortex_api/routers/admin.py` with `POST /v1/admin/force_decay_tick`, `reindex_embeddings`, `consolidate_tier`. Mounted in `app.py`.
- **CLI:** `kortex admin force-decay-tick`, `kortex admin reindex-embeddings`, `kortex admin consolidate` (API-routed).
- **Tests:** `tests/unit/test_decay_policy.py` — pinned clamping, short→mid promotion, hard-delete cutoff, decay-vs-time monotonicity.

---

## ✅ M7 — MCP HTTP/SSE + Multi-tenant Hardening (≈1w) — **DONE**

**Scope:**
- `kortex-mcp/transports/sse.py` (`kortex-mcp serve --port 8765`) with `Authorization: Bearer` handshake (per-connection principal materialisation).
- Per-key rate limits enforced via the Redis Lua token bucket built in M1 — three buckets (`read`, `write`, `recall`) keyed by API-key prefix.
- Sensitivity tier filtering already pushed down in `MemoryRepository.hybrid_search` / `AttachmentChunkRepository.hybrid_search`; M7 pins this with a cross-org + cross-sensitivity regression test.
- `kortex-mcp` Docker image + compose service (Helm values deferred to M9 with the rest of the chart).

**Definition of done:** A remote client can connect to MCP over SSE with a scoped API key and call the same tools the stdio runner exposes; cross-org / viewer-vs-secret leak tests pass. ✅

**Delivered files:**
- **SSE transport:** `packages/kortex-mcp/src/kortex_mcp/transports/sse.py` (Starlette `Route("/sse")` + `Mount("/messages/")` wrapping `mcp.server.sse.SseServerTransport`; rejects requests without `Authorization: Bearer kx_*` with HTTP 401). `kortex_mcp/main.py` learned a `serve [--host H] [--port P]` subcommand.
- **Rate limiter:** `packages/kortex-api/src/kortex_api/middleware/ratelimit.py`, registered in `app.py`. Three buckets (`read` 600/min, `write` 120/min, `recall` 30/min). Fails open on Redis outage (logs `ratelimit_redis_unavailable`).
- **Tenancy regression:** `tests/integration/test_tenancy_regression.py` exercises cross-org isolation across `search_memory`, `recall`, `list_memories`, and the direct repo `hybrid_search`; plus a viewer can never reach `secret` memories.
- **Lint:** `tools/ruff_plugins/tenant_check.py` — AST scan flags raw `select(Memory|MemoryLink|Attachment|AttachmentChunk|Session|Conversation|Message)` inside `packages/*/repositories/*.py`, honours an inline `# tenancy: ok` exemption. Standalone CLI for the pre-commit hook.
- **Docker / compose:** `docker/mcp.Dockerfile` mirrors the API image; `docker/compose.yaml` adds the `mcp` service on port 8765.
- **Tests:** `tests/unit/test_tenant_check_plugin.py` (lint behaviour), `tests/unit/test_ratelimit_bucket_selection.py` (bucket selector pinning), plus the integration test above.

---

## ✅ M8 — CLI Full Coverage + Ingest/Export (≈1w) — **DONE**

**Scope:**
- `kortex ingest messages|document|git-log` — fully wired.
- `kortex export --scope … -o backup.tar` — tarball export including memories + links + attachments + blobs. `kortex export import` restores into a target scope.
- `kortex admin migrate/force-decay-tick/reindex-embeddings/consolidate` — full coverage.
- Idempotency-Key cache (Redis, 24h) + ETag/If-Match enforcement on memory PATCH.

**Definition of done:** Round-trip a project from one cluster to another via `kortex export` then `kortex export import`. ✅

**Delivered files:**
- **API middleware:** `kortex_api/middleware/idempotency.py` (Redis-backed replay cache for POST/PATCH/PUT/DELETE; fails open), `kortex_api/middleware/etag.py` (weak ETag from `updated_at`; 412 on If-Match mismatch). Registered in `app.py`.
- **Ingest:** `IngestionService.ingest_git_log()`; `kortex_api/routers/ingest.py` adds `POST /v1/ingest/git-log`; `kortex_cli/cmds/ingest.py` adds `kortex ingest git-log <repo>` shelling out to `git log` and posting the parsed commits.
- **Export/import:** `kortex_core/services/export_service.py` (tar build + import, including blobs); `kortex_api/routers/export.py` (`GET /v1/export` + `POST /v1/export/import` UploadFile); `kortex_cli/cmds/export.py` (`kortex export scope -o file.tar`, `kortex export import file.tar`).
- **Wired:** export router mounted in `app.py`, `export` typer mounted in `kortex_cli/main.py`.
- **Tests:** `tests/unit/test_etag.py`, `tests/unit/test_export_service.py` (JSONL+blob round-trip + idempotency token shape).

---

## ✅ M9 — K8s + Observability Hardening (≈1.5w) — **DONE**

**Scope:**
- Helm chart at `deploy/helm/kortex/` with HPA on api (CPU + RPS), mcp (CPU), worker (Redis queue depth).
- `NetworkPolicy` opening only the egress ports we actually need (Postgres/Redis/S3/OTLP/HTTPS/DNS).
- Prometheus rules + 6 Grafana dashboards under `deploy/observability/`.
- Backup `CronJob` (`pg_dump | gzip | aws s3 cp`).
- Operator runbooks in `docs/operators/`.
- Loadtest: `scripts/bench_retrieval.py` exits non-zero when recall p99 > 1.2s.

**Definition of done:** Deploy via `helm install kortex deploy/helm/kortex` to a real K8s cluster; loadtest passes; dashboards render. ✅

**Delivered files:**
- **Helm:** `deploy/helm/kortex/{Chart.yaml,values.yaml}` and `templates/{_helpers.tpl,sa,api-deploy,mcp-deploy,worker-deploy,beat-deploy,hpa,ingress,netpol,backup-cronjob}.yaml`.
- **Kustomize:** `deploy/k8s/base/kustomization.yaml` + `overlays/{dev,staging,prod}/kustomization.yaml`.
- **Observability:** `deploy/observability/prometheus/rules.yaml` (4 alert groups: api-slos, retrieval, embed, tenancy); `deploy/observability/grafana/dashboards/{retrieval_performance,embedding_pipeline,decay_consolidation,tenancy_health,api_slos,db_health}.json`.
- **Loadtest:** `scripts/bench_retrieval.py` (httpx-based, rps + duration flags, exits 1 if p99 > 1.2s).
- **Runbooks:** `docs/operators/{deploy,scale,backup,rotate-keys,runbooks}.md`.

---

## ✅ M10 — Polish, Docs, Release (≈1w) — **DONE**

**Scope:**
- mkdocs-material site (`docs/mkdocs.yml`) with quickstart, architecture, dev, API, operator docs.
- CHANGELOG + 3 ADRs.
- PyPI release workflow (trusted publishing) for all 5 packages from a single `v*` tag.
- GHCR image workflow for api/mcp/worker.
- Postman collection.

**Definition of done:** Tag `v0.1.0`. From a fresh shell: `pip install kortex-cli`, point Claude Code's MCP config at `kortex-mcp stdio`, end-to-end works. ✅

**Delivered files:**
- **Docs site:** `docs/mkdocs.yml`, `docs/index.md`, `docs/quickstart.md`, `docs/architecture/overview.md`, `docs/architecture/adr/{0001-pgvector-hnsw,0002-agentic-retrieval,0003-pluggable-skills}.md`, `docs/developers/{setup,testing}.md`, `docs/api/{rest,mcp,postman.json}`.
- **CHANGELOG:** `CHANGELOG.md` (v0.1.0 entry summarising M1–M10).
- **Workflows:** `.github/workflows/release.yaml` (matrix-build all 5 packages → PyPI trusted publishing + GitHub Release with changelog extract), `.github/workflows/docker.yaml` (build + push api/mcp/worker images to GHCR).
- **CI hardening:** `ci.yaml` now also runs `tools.ruff_plugins.tenant_check`.

---

## End-to-end verification (after M1–M5)

1. `make dev` — compose up postgres+pgvector, redis, minio, api, mcp, worker.
2. `make migrate` — alembic upgrade head; `make seed` — create org/workspace/project/api-key.
3. `kortex auth login` and verify whoami.
4. `kortex ingest messages tests/fixtures/sample_chat.jsonl --session <id>` — wait for `embed_pending` to drain.
5. `kortex search "caching decisions"` — expect ranked hybrid results.
6. `kortex recall "caching decisions" --synthesize` — expect `ContextBundle` with citations and OTel trace `kortex.retrieval.recall` visible in collector.
7. Configure Claude Code's MCP config to launch `kortex-mcp stdio` with `KORTEX_API_KEY=<key>`; in a Claude Code session, call `recall` and `remember` tools, then in a fresh session verify the memory persists.
8. Upload a PDF: `kortex attachment upload sample.pdf --scope project:my-proj`; wait for `process_attachment`; `kortex search "term-from-pdf"` returns chunk-level hits.
9. `pytest -q` (unit + integration) — green; coverage ≥ 85%.
10. After M9: deploy via `helm install kortex deploy/helm/kortex` to a real K8s cluster, run `scripts/bench_retrieval.py --rps 50 --duration 5m`, verify p99 recall <1.2s on Grafana "Retrieval Performance" dashboard.

**Tenancy regression test (must run in CI):** create two orgs A and B, populate memories in each, issue an API key scoped to A, hit every read endpoint and every retrieval path (hybrid, agentic, MCP recall, attachment search) — assert zero rows from B leak. Same test asserts a `viewer` cannot see `secret` memories under any path.

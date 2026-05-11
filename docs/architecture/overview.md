# Architecture overview

```
                          ┌──────────────┐
   Claude Code / Codex ──▶│  MCP stdio   │
                          └──────┬───────┘
                                 │
   Browser / dashboard ──▶┌──────▼───────┐         ┌──────────────┐
                          │  kortex-api  │◀───────▶│ kortex-core  │
                          └──────┬───────┘         └──────┬───────┘
                                 │                        │
   Remote agents ──────▶┌─────── ▼──────┐                │
                        │  MCP SSE       │                │
                        └────────────────┘                │
                                                         ▼
                        ┌────────────────────┬───────────┴──────────┐
                        │  Postgres+pgvector │  Redis (queues, rate-│
                        │  (memories, links, │   limit, cache)      │
                        │  attachments)      │                      │
                        └────────────────────┴──────────────────────┘
                                                         │
                        ┌────────────────────┐           │
                        │ S3 / MinIO blobs   │◀──────────┘
                        └────────────────────┘
```

## Packages

- **kortex-core** — domain models, repos, services, retrieval, skills, embeddings, llm, storage, security, telemetry. The only package that talks to Postgres.
- **kortex-api** — FastAPI factory + routers + middleware (context, rate-limit, etag, idempotency).
- **kortex-mcp** — MCP server (stdio + SSE) sharing one tool registry.
- **kortex-cli** — `kortex` Typer CLI for admin + user surface.
- **kortex-worker** — Celery app + tasks (embed/decay/consolidate/summary/attachments) + beat.

## Tenancy

Every scoped row carries `org_id`. The single chokepoint is
`BaseRepository.tenant_query()`, which injects the org filter. A custom ruff
plugin (`tools/ruff_plugins/tenant_check.py`) flags any raw `select(Memory)`
inside `packages/*/repositories/` and a regression test
(`tests/integration/test_tenancy_regression.py`) asserts that no read path
leaks across orgs.

## Hybrid retrieval

`MemoryRepository.hybrid_search` runs a vector cosine kNN (HNSW) and a BM25
tsvector match in parallel, fuses results via Reciprocal Rank Fusion
(`k=60`), and applies a decay-score multiplier so faded memories rank lower.
Pinned memories get an RRF score floor so they always surface.

## Agentic retrieval (M5)

`AgenticRetriever` runs four phases:

1. **Plan** — planner LLM emits a `QueryPlan` (Pydantic).
2. **Execute** — `AgentLoop` dispatches the plan against `hybrid_search` and `memory_links` walks.
3. **Rerank** — `BgeReranker` (or `HeuristicReranker` fallback) rescores; `TokenBudget` packs.
4. **Synthesize** — summariser LLM produces a `ContextBundle` with `[m:public_id]` citations.

When the planner LLM is unavailable, recall transparently falls back to plain
hybrid retrieval with `plan_trace="fallback:hybrid"`.

## Decay & consolidation (M6)

Memories live in `short`/`mid`/`long` tiers. `decay_tick` (every 6h) scores
each non-pinned memory with `ExponentialDecayPolicy`. `consolidate_tier`
(daily 03:00 UTC) HDBSCAN-clusters mid-tier memories per org and asks the
LLM consolidator to write one long-tier summary per cluster, linked back via
`derived_from`.

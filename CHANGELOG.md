# Changelog

All notable changes to Kortex Memory are documented here. Versions follow
Semantic Versioning; pre-1.0 releases may include incidental schema changes.

## [Unreleased]

### Added
- **`kortex init <harness>`** — one command wires Claude Code, Cursor, Codex, or OpenCode to a
  Kortex install: resolves (or creates) the Project scope for the current git repo, mints a
  project-scoped API key, picks a transport (probes the MCP SSE endpoint, falls back to stdio),
  merges a server entry into the harness config, and verifies with a write→read canary. Merges are
  idempotent and never drop keys they did not add; an unparseable config aborts instead of being
  overwritten, and any file being replaced is backed up to `<name>.bak`. `--dry-run` reports without
  writing.
- **`kortex hook session-start`** — installed into `.claude/settings.json` by `kortex init`
  (skip with `--no-hooks`). Injects the project's memories into a starting Claude Code session.
  Fails silently by design: no credentials, no backend, or no project scope yields empty context
  and exit 0, so a memory lookup can never break a session.
- **Contradiction surfacing** — a memory that supersedes or contradicts an existing one now
  gets a `supersedes` / `contradicts` edge, written by a new `kortex.conflict.detect_pending`
  worker task (every 60s) over embedded, never-judged memories. Candidates are the nearest
  neighbours in the same scope and of the same kind, above a cosine-similarity floor; only
  `fact` / `preference` / `decision` are judged. Recall and search annotate every hit with its
  `conflicts`, and a memory superseded by another hit on the same page sorts last.
  **Conflicts are surfaced, never resolved** — nothing is filtered, merged, or deleted, because
  which side is right depends on conversation context the database does not have.
  Pluggable via the new `ConflictJudge` skill; with no LLM configured it degrades to
  `NullConflictJudge` and writes nothing. Off with `KORTEX_CONFLICT_DETECTION=false`.

- **Write-path integrity** — a memory whose embedding fails is no longer silently absent from
  vector search. A failed batch now falls back to per-item embedding, so one unembeddable input
  costs one memory instead of the whole batch; every failure increments `embed_attempts`, records
  the reason, and schedules an exponential backoff (capped at an hour); once attempts are
  exhausted the memory is *parked* (`embed_failed_at`) rather than retried forever. A short
  response from the embedder is caught too, instead of zip-truncating the tail away.
- **`GET /v1/admin/ingest-status`** — pending / failed / ok counts, the age of the oldest
  unembedded memory, and the most recent failures with their errors. Org-scoped for ordinary
  callers, fleet-wide for superusers.
- **`POST /v1/admin/retry_embeddings`** and **`kortex admin retry-embeddings`** — release parked
  memories back into the queue. Unlike `reindex_embeddings`, successful vectors are left alone.
- **`kortex doctor`** — checks the API, the credentials, and the embedding backlog, then writes a
  canary memory, waits for it to be embedded, searches for it, and deletes it. Non-zero exit on
  failure, so it works as a deploy gate or cron canary. `--skip-round-trip` for read-only checks.
- **`kortex admin ingest-status`** — the CLI view of the same counters.
- **Metrics + alerts** — `kortex_embed_pending`, `kortex_embed_failed`, and
  `kortex_embed_oldest_pending_seconds` on `/metrics` (refreshed on scrape, cached 15s), with
  `KortexEmbedFailures` / `KortexEmbedStalled` / `KortexEmbedPendingGrowing` alert rules and three
  new Grafana panels.
- **One-container local mode** — `docker run kortex/kortex:local` brings up Postgres + pgvector,
  Redis, the API, the MCP server, the worker and beat in a single container with a persistent
  volume, no checkout or compose file required. Attachments use the filesystem backend, so MinIO
  is gone from this path; a JWT secret is generated on first boot and persisted, so nobody
  evaluates Kortex on the insecure built-in default. `docker/compose.minimal.yaml` reuses the same
  image as a three-container stack with Postgres and Redis kept separate. Both are for evaluation
  and solo use, not production.
- **Repo hygiene** — `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue forms, and a PR
  template. `tests/e2e/` now exists, as the README has claimed since v0.1.

- **Benchmark harness** (`scripts/eval/`) — runs LongMemEval, LoCoMo, or a built-in synthetic
  suite against a live deployment over HTTP, reporting recall@k, MRR, judged accuracy (with
  `--judge`) and p50/p95/p99 latency for `hybrid` and `agentic` modes over the same corpus.
  Retrieval and answer accuracy are reported separately and never merged; unmeasured values render
  as `—` rather than zero. `docs/benchmarks.md` is the place results go — currently empty, and
  explicitly so.
- **Retrieval regression gate** (`tests/integration/test_retrieval_quality.py`) — scores a small
  synthetic corpus in ordinary CI and fails if recall or MRR falls below a floor, so a broken
  ranker fails on the PR that caused it. Floors are loose by design: it catches breakage, not
  drift.

- **Budget-aware recall** — `recall` / `get_context_bundle` accept `latency_budget_ms` and
  `token_budget`. A budget too small for an LLM planner round trip degrades to plain hybrid
  retrieval rather than overshooting, and `plan_rationale` records why, so a fast hybrid answer is
  distinguishable from a broken planner. The agent loop checks its remaining budget *before* each
  hop and returns what it has; synthesis is skipped when a second model call would not fit.
- **Cost and token reporting** — every recall response now carries `usage` with `mode`, token
  counts, `llm_calls`, `plan_steps`, `hops`, `latency_ms`, `cost_usd` and `budget_exhausted`.
  `cost_usd` is `null` unless the operator configures `KORTEX_LLM_PRICES`; null means unpriced,
  not free. This also fills the gap the benchmark harness reported as zero.

- **Deduplication on write** — writing a memory whose normalised title+body already exists in the
  same scope now folds into the existing one and returns it with `deduped: true`, instead of
  storing a second copy that competes for space in every future recall. The repeat counts as an
  access (so a re-remembered fact resists decay) and its metadata is merged rather than dropped.
  Scoped, never cross-scope. Bypass per write with `force`, or globally with
  `KORTEX_DEDUP_ON_WRITE=false`.

- **Voyage, Ollama and Bedrock embedders**, plus a **Bedrock LLM** adapter. Bedrock support was
  the single most-requested integration in the competitive research — usually not because of the
  model but because it keeps data inside an existing AWS account. Voyage and Ollama are plain HTTP
  and add no dependency; Bedrock reuses the `aiobotocore` stack the S3 backend already installs,
  and uses the Converse API so token usage is reported uniformly.
- **Embedding-dimension guard** — every vector column is `VECTOR(1024)`, so an embedder of any
  other width does not degrade quality, it stops writes entirely. Adapters now refuse to construct
  at the wrong width with a message naming the remedy, and Ollama re-checks on the first response
  because it serves whatever model was pulled. The width now lives in one constant that the models
  and the guard share, rather than as a literal in three model files.

- **Memory governance: PII detection, provenance trust, and prompt-injection quarantine.** A
  memory layer is a prompt-injection *persistence* layer — ordinary injection lasts one turn, but
  injection that gets stored is re-injected into every session that retrieves it. Three
  non-model defences, none of which can be talked out of their opinion:
  - Every write is scanned for personal and secret data. Checksummed where one exists (Luhn for
    cards, mod-97 for IBANs, SSA structural rules), because a false positive under redaction
    destroys data irreversibly. `pii_policy` chooses what a finding does: `tag` (default — record
    counts and change nothing), `redact`, or `escalate` (raise sensitivity so existing RBAC
    restricts reads). `pii_flags` stores counts by kind, never values.
  - Memories get a `trust` level from `source_type`. Low-trust content — fetched documents, tool
    output — is withheld from recalls made at confidential/secret sensitivity.
  - Low-trust content that reads as instructions to a model is **quarantined**: stored, but absent
    from every retrieval path until an operator releases it via `GET /v1/admin/quarantine` and
    `POST /v1/admin/quarantine/{id}/release`. Only low-trust content is scanned, so a person
    documenting an attack in their own notes is not quarantined for it.

### Changed
- Free plan raised from 1,000 to 25,000 memories.
- `search_memory` / `recall` / `get_context_bundle` responses gained a `conflicts` array per hit.
- `MemoryOut` gained `embedding_state` (`ok` / `pending` / `failed`), `embed_attempts`, and
  `embed_error`, so a client can tell whether a memory is actually searchable yet.
- `embed_pending` returns a result dict instead of a bare count.

### Fixed
- **Agentic recall crashed when the embedder was unavailable at call time.** The agent loop let
  `EmbeddingError` propagate out of a semantic-search step, so a missing optional dependency, a
  model that would not load, or a provider outage took the whole recall down — while every other
  retrieval path degrades to keyword-only. The step now falls back and the loop stops retrying an
  embedder that just failed.
- **`MissingGreenlet` on any async path that read a just-updated row.**
  `TimestampMixin.updated_at` uses `onupdate=func.now()`, a SQL expression the ORM cannot
  evaluate client-side, so after an UPDATE it marked the attribute expired; reading it then
  triggered a lazy refresh, which is synchronous IO inside an async context. MCP `end_session`
  and `update_memory` both returned an error to the agent instead of the updated row. The
  declarative base now sets `eager_defaults`, so Postgres returns the generated value with the
  UPDATE itself.
- `docs/mkdocs.yml` pointed `repo_url` at `github.com/anthropic/kortex-memory`, and did not
  exclude the internal strategy documents — mkdocs publishes every page it finds in `docs_dir`
  regardless of the nav, so the market research and implementation plan would have shipped to a
  public site.
- Dockerfiles are now built on pull requests. Nothing validated them until after merge to main.
- `tests/conftest.py` auto-marked tests by directory using a POSIX path check, so on Windows
  `pytest -m unit` silently selected only the few files carrying an explicit `pytestmark`.

## [0.1.0] — 2026-05-11

Initial release. All ten v0.1 milestones complete:

### Added
- **M1 Foundation** — uv workspace, kortex-core (settings/db/auth), kortex-api (auth/orgs/workspaces/projects/users/api_keys), kortex-cli, Docker compose, CI.
- **M2 Memories + Hybrid Search** — session/memory models (Alembic 0002), pluggable `Embedder` protocol with `LocalBgeEmbedder` default, hybrid retrieval substrate (vector + BM25 + RRF + decay), CRUD APIs/CLI, `embed_pending` worker.
- **M3 MCP stdio** — `kortex-mcp stdio` with 12 canonical tools sharing the same tool registry the SSE transport will reuse.
- **M4 Attachments + S3** — `BlobStore` protocol with S3/FS adapters, `Attachment` + `AttachmentChunk` (Alembic 0003), `process_attachment` worker (PyMuPDF/python-docx), API/CLI/MCP `attach_file`/`finalize_attachment`/`get_attachment`.
- **M5 Agentic Retrieval** — `LLM` protocol with Anthropic/OpenAI/OpenRouter/Ollama adapters, `Reranker` skill (`BgeReranker` default + `HeuristicReranker` fallback), `QueryPlan`/`AgentLoop`, `AgenticRetriever` with `ContextBundle`, `POST /v1/search/recall`, MCP `recall` upgrade + `get_context_bundle`, OTel spans across `kortex.retrieval.*`.
- **M6 Decay / Consolidation / Skills** — formalised 5 skill protocols (`DecayPolicy`, `ImportanceScorer`, `Summarizer`, `Consolidator`, `AccessPolicy`), decay/consolidate/summary worker tasks + beat schedule (6h / daily 03:00 UTC / 5min), admin endpoints `force_decay_tick` / `reindex_embeddings` / `consolidate_tier`.
- **M7 MCP SSE + Tenancy Hardening** — `kortex-mcp serve` SSE transport with per-connection Bearer auth, API rate-limit middleware (3 buckets), cross-org + cross-sensitivity regression test, `tenant_check` ruff plugin, MCP Docker image.
- **M8 CLI Full Coverage + Ingest/Export** — `kortex ingest git-log`, `kortex export` / `kortex export import` (tar with memories + links + attachments + blobs), Idempotency-Key middleware (24h Redis cache), ETag/If-Match enforcement on memory PATCH.
- **M9 K8s + Observability** — Helm chart (`deploy/helm/kortex`), kustomize overlays (`dev`/`staging`/`prod`), Prometheus rules + 6 Grafana dashboards, `bench_retrieval.py`, operator runbooks (`deploy`/`scale`/`backup`/`rotate-keys`/`runbooks`).
- **M10 Polish + Docs + Release** — mkdocs-material site, 3 ADRs, REST + MCP API docs, CHANGELOG, GitHub Actions release + docker workflows, Postman collection placeholder.

### Notes
- Schema: 3 Alembic migrations (`kkx0001`–`kkx0003`).
- Tools surface: 16 MCP tools.
- 5 PyPI packages: `kortex-core`, `kortex-api`, `kortex-mcp`, `kortex-cli`, `kortex-worker`.
- 3 GHCR images: `kortex-api`, `kortex-mcp`, `kortex-worker`.

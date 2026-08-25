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

### Changed
- Free plan raised from 1,000 to 25,000 memories.
- `search_memory` / `recall` / `get_context_bundle` responses gained a `conflicts` array per hit.
- `MemoryOut` gained `embedding_state` (`ok` / `pending` / `failed`), `embed_attempts`, and
  `embed_error`, so a client can tell whether a memory is actually searchable yet.
- `embed_pending` returns a result dict instead of a bare count.

### Fixed
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

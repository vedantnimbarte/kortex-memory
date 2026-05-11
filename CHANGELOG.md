# Changelog

All notable changes to Kortex Memory are documented here. Versions follow
Semantic Versioning; pre-1.0 releases may include incidental schema changes.

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

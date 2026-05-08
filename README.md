# kortex-memory

Production-grade, multi-tenant memory layer for LLMs and AI coding agents (Claude Code, Codex, OpenCode, others). Plug it in via MCP and your agents get a shared, durable, scoped, access-controlled memory that survives across sessions and tools.

## Highlights

- **MCP server** with both stdio and HTTP/SSE transports.
- **REST API** with full coverage of memories, conversations, attachments, and tenancy.
- **CLI** (`kortex`) for admin and user workflows.
- **Postgres + pgvector** for chats, atomic memories, and vector search.
- **S3-compatible attachments** (MinIO in dev, S3/R2 in prod).
- **Agentic retrieval** — an LLM plans multi-hop hybrid (vector + BM25 + recency) lookups.
- **Short / mid / long-term tiers** with auto promotion, decay, and consolidation.
- **Sensitivity tiers × RBAC** for fine-grained access control.
- **OpenTelemetry** traces, Prometheus metrics, structured JSON logs from day one.

## Project layout

```
kortex-memory/
├── packages/
│   ├── kortex-core/    # domain models, repos, services, retrieval, skills
│   ├── kortex-api/     # FastAPI REST app
│   ├── kortex-mcp/     # MCP server (stdio + SSE)
│   ├── kortex-cli/     # `kortex` Typer CLI
│   └── kortex-worker/  # Celery worker + beat
├── alembic/            # migrations
├── docker/             # Dockerfiles + compose.yaml
├── deploy/{helm,k8s}/  # production manifests
└── tests/              # unit, integration, e2e
```

## Quickstart (dev)

```bash
uv sync
docker compose -f docker/compose.yaml up -d
make migrate
make seed
kortex auth login
```

See `docs/` for the full architecture and operator guide.

## License

Apache-2.0.

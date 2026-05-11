# kortex-memory

Production-grade, multi-tenant memory layer for LLMs and AI coding agents
(Claude Code, Codex, OpenCode). Plug it in via MCP and your agents get a
shared, durable, scoped, access-controlled memory that survives across
sessions and tools.

## Highlights

- **MCP server** with both stdio and HTTP/SSE transports (16 canonical tools).
- **REST API** with full coverage of memories, conversations, attachments, ingest, export, and tenancy.
- **CLI** (`kortex`) for admin + day-to-day workflows.
- **Postgres + pgvector** for memories, sessions, and vector search.
- **S3-compatible attachments** (MinIO in dev, S3/R2 in prod).
- **Agentic retrieval** — an LLM plans multi-hop hybrid (vector + BM25 + recency) lookups; clean fallback to plain hybrid when the planner LLM is unavailable.
- **Short / mid / long-term tiers** with auto-promotion, decay, and HDBSCAN consolidation.
- **Sensitivity tiers × RBAC** for fine-grained access control.
- **OpenTelemetry traces, Prometheus metrics, structured JSON logs** from day one.
- **Idempotency-Key + ETag/If-Match** on the API for safe client retries.

## Documentation

| Doc | Read when |
|---|---|
| [RUNNING_LOCALLY.md](RUNNING_LOCALLY.md) | You want to try Kortex on your machine and wire Claude Code to it. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | You're shipping Kortex to a real Kubernetes cluster. |
| [RELEASE.md](RELEASE.md) | You're cutting a new tagged release. |
| [CHANGELOG.md](CHANGELOG.md) | You want to know what changed in this version. |
| [docs/](docs/) | The full mkdocs site (architecture, ADRs, ops runbooks, API ref). |

## Project layout

```
kortex-memory/
├── packages/
│   ├── kortex-core/    # domain models, repos, services, retrieval, skills, llm, storage
│   ├── kortex-api/     # FastAPI REST app (+ middleware: context, etag, idempotency, ratelimit)
│   ├── kortex-mcp/     # MCP server (stdio + SSE) sharing one tool registry
│   ├── kortex-cli/     # `kortex` Typer CLI (admin + user)
│   └── kortex-worker/  # Celery worker (embed, decay, consolidate, attachments, summaries) + beat
├── alembic/            # migrations (3 revisions)
├── docker/             # api/mcp/worker Dockerfiles + compose.yaml
├── deploy/
│   ├── helm/kortex/    # production Helm chart
│   ├── k8s/            # kustomize base + overlays (dev/staging/prod)
│   └── observability/  # Prometheus rules + 6 Grafana dashboards
├── docs/               # mkdocs-material site
├── tools/              # custom CI lints (e.g. tenancy chokepoint)
└── tests/              # unit, integration, e2e
```

## 30-second tour

```bash
# Local dev — full stack in Docker
uv sync
make dev && make migrate && make seed

# Try it
export KORTEX_API_URL=http://localhost:8000
export KORTEX_API_KEY=<printed by make seed>
kortex memory create --body "Use Redis with a 5-min TTL for the search cache"
kortex search "caching"
kortex recall "what did we decide about caching?" --synthesize

# Wire Claude Code → add this to your MCP config:
#   { "command": "kortex-mcp", "args": ["stdio"], "env": { "KORTEX_API_KEY": "..." } }
```

Full walk-through in [RUNNING_LOCALLY.md](RUNNING_LOCALLY.md).

## License

Apache-2.0.

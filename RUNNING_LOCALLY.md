# Running Kortex Locally

This guide takes you from a fresh clone to a Claude Code agent talking to your
memory layer in under 15 minutes.

> **Need to deploy to a real cluster?** See [DEPLOYMENT.md](DEPLOYMENT.md).
>
> **TL;DR for veterans:** `uv sync && make dev && make migrate && make seed`.
> Use the printed API key in your Claude Code MCP config.

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | **3.12.x** (not 3.11, not 3.13) | All packages pin `>=3.12,<3.13`. |
| `uv` | 0.4+ | Workspace install + lock. |
| Docker + Docker Compose | recent | Brings up Postgres+pgvector, Redis, MinIO. |
| Git | any | Cloning + the `kortex ingest git-log` flow. |

**Optional:**

- An Anthropic API key (`ANTHROPIC_API_KEY=...`) if you want agentic recall.
  Without it the retrieval engine cleanly falls back to plain hybrid search.
- ~3 GB free disk if you want the local BGE embeddings (`BAAI/bge-large-en-v1.5`
  pulls from Hugging Face on first use).

---

## 2. Clone + install

```bash
git clone git@github.com:vedantnimbarte/kortex-memory.git
cd kortex-memory
uv sync --all-packages
```

`uv sync` reads the workspace `pyproject.toml` and installs every package
plus the dev tooling (`pytest`, `ruff`, `mypy`, `testcontainers`).

---

## 3. Start the supporting services

```bash
make dev
```

This runs `docker compose -f docker/compose.yaml up -d` and starts:

| Service | Port | Purpose |
|---|---|---|
| `postgres` (pgvector/pgvector:pg16) | 5432 | Memories, embeddings, FTS |
| `redis` | 6379 | Celery broker, rate-limit buckets, idempotency cache |
| `minio` | 9000 (API), 9001 (console) | S3-compatible blob storage |
| `minio-init` | — | One-shot job creating the `kortex-attachments` bucket |
| `api` | 8000 | FastAPI REST |
| `mcp` | 8765 | MCP HTTP/SSE |
| `worker` | — | Celery worker (embed, decay, consolidate, attachments) |
| `beat` | — | Celery beat scheduler |

Verify with `docker compose -f docker/compose.yaml ps` — all services should
report `healthy`. To tail logs: `make logs`.

> **Skip the compose API/MCP/worker** and run them on your host if you want
> live-reload during development:
>
> ```bash
> docker compose -f docker/compose.yaml up -d postgres redis minio minio-init
> uv run kortex-api &
> uv run kortex-worker worker &
> uv run kortex-worker beat &
> ```

---

## 4. Apply migrations

```bash
make migrate    # equivalent to: uv run alembic upgrade head
```

This creates extensions (`pgvector`, `pg_trgm`, `citext`, `uuid-ossp`), all
enums, and every table (tenancy, memories, sessions, attachments). Re-running
is a no-op.

---

## 5. Seed an org + admin + API key

```bash
make seed    # equivalent to: uv run python scripts/seed_dev.py
```

Output looks like:

```
============================================================
kortex dev seed complete
  org:        kortex (id=1)
  workspace:  default (id=1)
  project:    playground (id=1)
  admin:      admin@kortex.local / kortex-dev-password
  api key:    kx_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
============================================================
```

**The plaintext API key is shown exactly once.** Copy it.

> Customise via env vars: `KORTEX_SEED_EMAIL`, `KORTEX_SEED_PASSWORD`,
> `KORTEX_SEED_ORG`, `KORTEX_SEED_WORKSPACE`, `KORTEX_SEED_PROJECT`.

---

## 6. Configure your CLI / shell

```bash
export KORTEX_API_URL=http://localhost:8000
export KORTEX_API_KEY=kx_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Or persist as a CLI profile:
mkdir -p ~/.config/kortex
cat > ~/.config/kortex/config.toml <<'EOF'
[default]
api_url = "http://localhost:8000"
api_key = "kx_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
EOF
```

---

## 7. Sanity-check the API

```bash
# Health
curl http://localhost:8000/livez
curl http://localhost:8000/readyz

# Whoami / create a memory / search
kortex memory create --body "Use Redis with a 5min TTL for the search cache" \
  --scope-type project --scope-id 1 --embed
kortex search "caching strategy"
kortex recall "what did we decide about caching?" --synthesize
```

If `--synthesize` returns "planner unavailable; ran plain hybrid retrieval" —
that's expected without `ANTHROPIC_API_KEY`. The fallback path is correct.

---

## 8. Wire Claude Code to your local Kortex

Add to your Claude Code MCP config (typically
`~/.config/claude-code/mcp_servers.json` or via `claude code config mcp`):

```json
{
  "mcpServers": {
    "kortex": {
      "command": "kortex-mcp",
      "args": ["stdio"],
      "env": {
        "KORTEX_API_KEY": "kx_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "KORTEX_DATABASE_URL": "postgresql+asyncpg://kortex:kortex@localhost:5432/kortex",
        "KORTEX_REDIS_URL": "redis://localhost:6379/0"
      }
    }
  }
}
```

Restart Claude Code. Your agent now sees 16 tools: `remember`, `recall`,
`search_memory`, `get_memory`, `list_memories`, `update_memory`,
`delete_memory`, `link_memories`, `pin_memory`, `start_session`,
`end_session`, `list_sessions`, `attach_file`, `finalize_attachment`,
`get_attachment`, `get_context_bundle`.

---

## 9. Try the agentic recall path (optional)

Export an Anthropic key and rerun the synthesize call:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
kortex recall "what did we decide about caching?" --synthesize
```

You should see a structured answer with `[m:public_id]` citations and a
`plan_trace` showing the planner's steps.

---

## 10. Run the tests

```bash
make test-unit              # fast, process-local
make test-integration       # spins up testcontainers; needs Docker
make test                   # both
```

Coverage gate is 85%. Lint + types:

```bash
make lint
make type
uv run python -m tools.ruff_plugins.tenant_check .
```

---

## Common dev tasks

### Reset the database

```bash
docker compose -f docker/compose.yaml down -v
make dev && make migrate && make seed
```

### Tail Celery worker logs

```bash
docker compose -f docker/compose.yaml logs -f worker beat
```

### Upload an attachment

```bash
kortex attachment upload ~/Downloads/design.pdf \
  --scope-type project --scope-id 1
kortex attachment list --scope-type project --scope-id 1
kortex attachment search "term-from-pdf"
```

`process_attachment` runs in the worker; if you see status `pending`/`processing`
for too long, check `make logs`.

### Export & re-import a project

```bash
kortex export scope --scope-type project --scope-id 1 -o /tmp/proj.tar
kortex export import /tmp/proj.tar --target-scope-type project --target-scope-id 2
```

### Admin: force a decay tick or reindex

```bash
kortex admin force-decay-tick
kortex admin reindex-embeddings
kortex admin consolidate
```

These dispatch Celery tasks; watch them complete in the worker logs.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `unable to connect to postgres` | Postgres not up yet | `docker compose ps`; retry after `healthy` |
| `pgvector extension not found` | Wrong Postgres image | Use `pgvector/pgvector:pg16` (compose default) |
| `KORTEX_API_KEY required` from `kortex-mcp` | Env not exported | Export it or put it in Claude Code's `env` block |
| MCP tools missing in Claude Code | MCP server failed to launch | Run `kortex-mcp stdio` manually; check stderr |
| `embed_pending` not draining | Worker not running | `make logs` → restart `worker` |
| Inline embedding hangs on first call | Hugging Face download | Wait — `BAAI/bge-large-en-v1.5` is ~1.3 GB |
| Recall always falls back to hybrid | Missing `ANTHROPIC_API_KEY` | Export it, restart `api` |

For deeper issues, the `docs/operators/runbooks.md` page has a triage tree.

---

## What next?

- [DEPLOYMENT.md](DEPLOYMENT.md) — production install on Kubernetes / Helm.
- [docs/architecture/overview.md](docs/architecture/overview.md) — how the pieces fit together.
- [docs/api/rest.md](docs/api/rest.md) and [docs/api/mcp.md](docs/api/mcp.md) — full API surfaces.
- [CHANGELOG.md](CHANGELOG.md) — what's in this release.

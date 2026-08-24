# kortex-memory

Production-grade, multi-tenant memory layer for LLMs and AI coding agents
(Claude Code, Codex, OpenCode). Plug it in via MCP and your agents get a
shared, durable, scoped, access-controlled memory that survives across
sessions and tools.

## Highlights

- **MCP server** with both stdio and HTTP/SSE transports (16 canonical tools).
- **REST API** with full coverage of memories, conversations, attachments, ingest, export, and tenancy.
- **Web console** (`kortex-web`) — Vite + React SPA for recall, memory browsing, ingest, API keys, and billing.
- **CLI** (`kortex`) for admin + day-to-day workflows.
- **Postgres + pgvector** for memories, sessions, and vector search.
- **S3-compatible attachments** (MinIO in dev, S3/R2 in prod).
- **Agentic retrieval** — an LLM plans multi-hop hybrid (vector + BM25 + recency) lookups; clean fallback to plain hybrid when the planner LLM is unavailable.
- **Short / mid / long-term tiers** with auto-promotion, decay, and HDBSCAN consolidation.
- **Contradiction surfacing** — when a memory supersedes or contradicts an older one, recall
  returns both, flags the stale side, and sorts it last. Surfaced, never auto-resolved.
- **Sensitivity tiers × RBAC** for fine-grained access control.
- **OpenTelemetry traces, Prometheus metrics, structured JSON logs** from day one.
- **Idempotency-Key + ETag/If-Match** on the API for safe client retries.

## Documentation

| Doc | Read when |
|---|---|
| **This README** | You want the fast path: everything running locally in Docker, or a deploy at a glance. |
| [RUNNING_LOCALLY.md](RUNNING_LOCALLY.md) | You want the full local walk-through (CLI profiles, agentic recall, troubleshooting). |
| [DEPLOYMENT.md](DEPLOYMENT.md) | You're shipping Kortex to a real Kubernetes cluster (full runbook). |
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
│   ├── kortex-web/     # Vite + React + TypeScript web console (SPA)
│   └── kortex-worker/  # Celery worker (embed, decay, consolidate, attachments, summaries) + beat
├── alembic/            # database migrations
├── docker/             # api/mcp/worker/web Dockerfiles + compose.yaml + web-nginx.conf
├── deploy/
│   ├── helm/kortex/    # production Helm chart (api, mcp, worker, web)
│   ├── k8s/            # kustomize base + overlays (dev/staging/prod)
│   └── observability/  # Prometheus rules + 6 Grafana dashboards
├── docs/               # mkdocs-material site
├── scripts/            # dev seed + helpers
├── tools/              # custom CI lints (e.g. tenancy chokepoint)
└── tests/              # unit, integration, e2e
```

---

# Running everything locally

The full stack — Postgres, Redis, MinIO, API, MCP, worker, beat, and the web
console — runs in Docker. You only need Python + `uv` on your host to run
migrations and the CLI, and (optionally) Node if you want live-reload frontend
development.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Docker + Docker Compose | recent | Brings up the whole stack (db, cache, blob store, services). |
| Python | **3.12.x** (not 3.11, not 3.13) | Packages pin `>=3.12,<3.13`; needed for migrations + CLI. |
| `uv` | 0.4+ | Workspace install, migrations, seeding. |
| Node + npm | 20+ | Only for `kortex-web` dev server (hot reload). Skip if you run the web container. |
| Git | any | Cloning + the `kortex ingest git-log` flow. |

**Optional:** an `ANTHROPIC_API_KEY` for agentic recall (retrieval cleanly
falls back to plain hybrid search without it), and ~3 GB free disk for the
local BGE embeddings (`BAAI/bge-large-en-v1.5`, pulled from Hugging Face on
first use).

## 1. Clone + configure

```bash
git clone git@github.com:vedantnimbarte/kortex-memory.git
cd kortex-memory

cp .env.example .env                              # backend config (see table below)
cp packages/kortex-web/.env.example packages/kortex-web/.env   # frontend config
uv sync --all-packages                            # install every package + dev tooling
```

The compose file injects its own service-to-service env (Postgres/Redis/MinIO
hostnames), so the defaults in `.env.example` work out of the box. Edit `.env`
only to add secrets like `ANTHROPIC_API_KEY` or Stripe keys.

## 2. Bring up the stack

```bash
make dev        # docker compose -f docker/compose.yaml up -d
```

| Service | Port | Purpose |
|---|---|---|
| `postgres` (pgvector/pgvector:pg16) | 5432 | Memories, embeddings, FTS |
| `redis` | 6379 | Celery broker, rate-limit buckets, idempotency cache |
| `minio` | 9000 (API), 9001 (console) | S3-compatible blob storage |
| `minio-init` | — | One-shot job creating the `kortex-attachments` bucket |
| `api` | 8000 | FastAPI REST |
| `mcp` | 8765 | MCP HTTP/SSE |
| `worker` / `beat` | — | Celery worker + scheduler (embed, decay, consolidate, attachments) |
| `web` | 5173 | Web console (nginx serving the built SPA, proxies `/v1` → api) |

Check status with `docker compose -f docker/compose.yaml ps` (all should report
`healthy`); tail logs with `make logs`.

> **Live-reload backend?** Run the deps in Docker and the services on your host:
> ```bash
> docker compose -f docker/compose.yaml up -d postgres redis minio minio-init
> uv run kortex-api & uv run kortex-worker worker & uv run kortex-worker beat &
> ```

## 3. Migrate the database

```bash
make migrate    # uv run alembic upgrade head
```

Creates the extensions (`pgvector`, `pg_trgm`, `citext`, `uuid-ossp`), all
enums, and every table (tenancy, memories, sessions, attachments). Re-running
is a no-op.

## 4. Seed an org + admin + API key

```bash
make seed       # uv run python scripts/seed_dev.py
```

Prints a dev org, workspace, project, admin login
(`admin@kortex.dev` / `kortex-dev-password`), and a plaintext API key
(`kx_...`) **shown exactly once — copy it.** Customise via `KORTEX_SEED_EMAIL`,
`KORTEX_SEED_PASSWORD`, `KORTEX_SEED_ORG`, `KORTEX_SEED_WORKSPACE`,
`KORTEX_SEED_PROJECT`.

## 5. Verify

```bash
curl http://localhost:8000/livez && curl http://localhost:8000/readyz

export KORTEX_API_URL=http://localhost:8000
export KORTEX_API_KEY=kx_...            # from make seed
kortex memory create --body "Use Redis with a 5-min TTL for the search cache" \
  --scope-type project --scope-id 1 --embed
kortex search "caching"
kortex recall "what did we decide about caching?" --synthesize
```

Open the web console at **http://localhost:5173** and log in with the seeded
admin credentials.

> `--synthesize` returning "planner unavailable; ran plain hybrid retrieval"
> without `ANTHROPIC_API_KEY` is expected — the fallback path is correct.

## Running the frontend (`kortex-web`)

Two paths, both against the same local API on `:8000`:

**A. Vite dev server (hot reload — the frontend dev loop):**

```bash
cd packages/kortex-web
npm install
npm run dev        # http://localhost:5173, proxies /v1 -> http://localhost:8000
```

No CORS config needed — the Vite proxy handles it. Run the API alongside it
(the compose `api` service, or `uv run kortex-api`).

**B. Compose `web` service (no Node needed):** already started by `make dev`.
nginx serves the production build on `:5173` and proxies `/v1` to the api
service. No hot reload — rebuild with
`docker compose -f docker/compose.yaml up -d --build web` after changes.

Build/preview standalone: `npm run build` (→ `dist/`), `npm run preview`.

## Environment variables

Backend config lives in **`.env`** (`.env.example` is the template). Frontend
config lives in **`packages/kortex-web/.env`**. Defaults work for local Docker;
you only need to set the secrets.

| Group | Key(s) | Notes |
|---|---|---|
| **Database** | `KORTEX_DATABASE_URL` | `postgresql+asyncpg://kortex:kortex@localhost:5432/kortex` (host) / `@postgres:` (in compose). |
| **Redis** | `KORTEX_REDIS_URL` | Celery broker + rate limiting. `redis://localhost:6379/0`. |
| **S3 / MinIO** | `KORTEX_S3_ENDPOINT_URL`, `KORTEX_S3_BUCKET`, `KORTEX_S3_ACCESS_KEY`, `KORTEX_S3_SECRET_KEY`, `KORTEX_S3_REGION`, `KORTEX_S3_USE_SSL` | MinIO defaults `minioadmin`/`minioadmin`; point at real S3/R2 in prod. |
| **Auth** | `KORTEX_JWT_SECRET`, `KORTEX_JWT_ALGORITHM`, `KORTEX_JWT_ACCESS_TTL_SECONDS`, `KORTEX_JWT_REFRESH_TTL_SECONDS` | **Set a real random 32-byte `KORTEX_JWT_SECRET` outside dev.** |
| **Embeddings** | `KORTEX_EMBEDDER`, `KORTEX_EMBEDDER_MODEL`, `KORTEX_EMBEDDER_DIM` | Default local BGE (`BAAI/bge-large-en-v1.5`, dim 1024). |
| **LLM** | `KORTEX_LLM_PROVIDER`, `KORTEX_LLM_MODEL_PLANNER`, `KORTEX_LLM_MODEL_SUMMARIZER`, `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` optional; enables agentic recall. |
| **Retrieval** | `KORTEX_AGENTIC_RETRIEVAL`, `KORTEX_RETRIEVAL_MAX_HOPS`, `KORTEX_RETRIEVAL_MAX_CANDIDATES` | Tuning knobs for the planner. |
| **Email** | `KORTEX_EMAIL_BACKEND`, `KORTEX_EMAIL_FROM`, `KORTEX_WEB_BASE_URL`, `KORTEX_SMTP_*` | `log` backend prints verify links to logs in dev; `smtp` for real delivery. |
| **Billing (Stripe)** | `KORTEX_STRIPE_SECRET_KEY`, `KORTEX_STRIPE_WEBHOOK_SECRET`, `KORTEX_STRIPE_PRICE_*`, `KORTEX_BILLING_*_URL` | Optional; unset = billing runs in preview (checkout disabled). |
| **API** | `KORTEX_API_HOST`, `KORTEX_API_PORT`, `KORTEX_API_CORS_ORIGINS` | Add prod SPA origin(s) to CORS when deploying. |
| **Telemetry** | `KORTEX_OTEL_*`, `KORTEX_LOG_LEVEL`, `KORTEX_LOG_JSON` | OTEL off by default locally. |
| **Environment** | `KORTEX_ENV` | `development` / `production`. |
| **Frontend** | `VITE_API_BASE_URL` | Blank in dev (Vite proxy). Set to the API origin in prod, e.g. `https://api.kortex.example.com`. |

## Wire an agent to your local Kortex

One command per harness — Claude Code, Cursor, Codex, or OpenCode:

```bash
kortex init claude-code
```

It finds (or creates) the Project scope for the current git repo, mints a
project-scoped API key, picks a transport (SSE if the MCP service is up, stdio
otherwise), writes the harness config, and verifies with a write→read canary.
Re-running is a no-op, `--dry-run` shows what it would do, and any file it
replaces is backed up to `<name>.bak`.

For Claude Code it also installs a `SessionStart` hook that injects the
project's memories into every new session (`--no-hooks` to skip).

Restart the agent — it now sees the 16 Kortex tools.

<details>
<summary>Prefer to wire it by hand?</summary>

```json
{
  "mcpServers": {
    "kortex": {
      "command": "kortex-mcp",
      "args": ["stdio"],
      "env": {
        "KORTEX_API_KEY": "kx_...",
        "KORTEX_DATABASE_URL": "postgresql+asyncpg://kortex:kortex@localhost:5432/kortex",
        "KORTEX_REDIS_URL": "redis://localhost:6379/0"
      }
    }
  }
}
```

</details>

Full detail, CLI profiles, and troubleshooting in [RUNNING_LOCALLY.md](RUNNING_LOCALLY.md).

## Common tasks

```bash
make test-unit          # fast, process-local
make test-integration   # testcontainers; needs Docker
make test               # both (coverage gate 85%)
make lint && make type  # ruff + mypy
uv run python -m tools.ruff_plugins.tenant_check .   # tenancy chokepoint lint

# Reset the database
docker compose -f docker/compose.yaml down -v && make dev && make migrate && make seed

make down               # stop the stack
make logs               # tail all service logs
```

---

# Deploying to Kubernetes

Full runbook (secrets, provider matrix, backups, observability, smoke tests) is
in **[DEPLOYMENT.md](DEPLOYMENT.md)**. At a glance:

```bash
# 1. Namespace + secrets (S3, JWT, LLM)
kubectl create namespace kortex
kubectl -n kortex create secret generic kortex-s3  --from-literal=... 
kubectl -n kortex create secret generic kortex-jwt --from-literal=...
kubectl -n kortex create secret generic kortex-llm --from-literal=ANTHROPIC_API_KEY=...

# 2. Run migrations as a one-shot pod
kubectl -n kortex run --rm -it migrate --image=<your-registry>/kortex-api:<tag> \
  --command -- alembic upgrade head

# 3a. Install via Helm (api, mcp, worker, web + ingress)
helm install kortex deploy/helm/kortex --namespace kortex \
  --set postgres.url='postgresql+asyncpg://kortex:PASSWORD@pg.svc:5432/kortex' \
  --set redis.url='redis://redis.svc:6379/0' \
  --set s3.endpointUrl='https://s3.amazonaws.com' --set s3.bucket='kortex-prod-attachments' \
  --set api.ingress.host='kortex.example.com' --set api.ingress.tlsSecret='kortex-tls' \
  --set image.api.tag='0.1.0' --set image.mcp.tag='0.1.0' --set image.worker.tag='0.1.0'

# 3b. …or Kustomize overlays (dev / staging / prod)
kubectl kustomize deploy/k8s/overlays/prod | kubectl apply -f -
```

Postgres, Redis, and object storage are **not** installed by the chart — point
it at managed services (or your own operators). The ingress routes API paths to
the `api` service and everything else to the `web` SPA. See DEPLOYMENT.md for
the full sequence including smoke tests, backups, and the load-test gate.

## License

Apache-2.0.

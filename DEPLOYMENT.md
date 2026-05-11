# Deploying Kortex

Production deployment guide. The supported install path is **Helm on
Kubernetes**; smaller installs can run on Docker Compose. This document
covers both.

> **For local development**, use [RUNNING_LOCALLY.md](RUNNING_LOCALLY.md) instead.
> The pages under `docs/operators/` (deploy, scale, backup, rotate-keys,
> runbooks) cover ongoing operations once the system is live.

---

## What you're deploying

```
                          ┌──────────────┐
   Claude Code / Codex ──▶│  MCP stdio   │ (subprocess, local to agent)
                          └──────────────┘

   Web / dashboard ─────▶┌─────────────┐
                         │ kortex-api  │── /v1/*  HTTPS
                         └──────┬──────┘
   Remote agents ───────▶┌──────▼──────┐
                         │ kortex-mcp  │── /sse  HTTPS (Bearer auth)
                         └──────┬──────┘
                                │
                  ┌─────────────┴─────────────┐
                  │   Postgres + pgvector     │   ← stateful, you own this
                  │   Redis                   │   ← queues + cache
                  │   S3 / R2 / MinIO         │   ← attachments + backups
                  └───────────────────────────┘
                                │
                  ┌─────────────▼─────────────┐
                  │ kortex-worker + beat      │   ← Celery (embed, decay,
                  └───────────────────────────┘     consolidate, summaries)
```

Five workloads ship in the Helm chart:

- `kortex-api` — Deployment + Service + Ingress + HPA (CPU + RPS).
- `kortex-mcp` — Deployment + Service + HPA (CPU).
- `kortex-worker` — Deployment + HPA (Redis queue depth).
- `kortex-beat` — single replica (Recreate strategy).
- `kortex-backup` — daily CronJob.

Plus a `NetworkPolicy` and `ServiceAccount`.

---

## Prerequisites

| Component | Version | Notes |
|---|---|---|
| Kubernetes | 1.28+ | HPA v2 with custom metrics is assumed. |
| Helm | 3.13+ | Render-only is fine if you prefer `helm template \| kubectl apply`. |
| Postgres | **16+** with `pgvector >= 0.7` and `pg_trgm`, `citext`, `uuid-ossp` extensions | Managed (RDS / Cloud SQL / Crunchy) or self-hosted. Min 4 vCPU / 8 GB RAM for production. |
| Redis | 7.x | Min `maxmemory 1gb` with `allkeys-lru`. |
| S3-compatible store | any | AWS S3, R2, GCS in S3 mode, or MinIO. |
| `prometheus-adapter` + `metrics-server` | latest | For the HPA custom metrics (`kortex_api_requests_per_second`, `redis_queue_depth`). |
| `cert-manager` (optional but recommended) | latest | TLS issuance for the API/MCP ingress. |
| OTel collector | optional | If you want traces/metrics exported via OTLP/gRPC. |

---

## Step 0 — Decide your provider matrix

Pick now, configure once:

| Choice | Default | Alternative |
|---|---|---|
| Embedder | `local_bge` (BAAI/bge-large-en-v1.5, ~1.3 GB on worker pods) | `openai`, `voyage`, `cohere` |
| LLM provider | `anthropic` (claude-sonnet-4-7 / claude-haiku-4-5) | `openai`, `openrouter`, `ollama` |
| Storage | `s3` (production) | `fs` (tests only) |

`KORTEX_AGENTIC_RETRIEVAL=true` requires an LLM provider key. Without one, the
chart will deploy and recall falls back to plain hybrid retrieval — fine for a
day-one launch.

---

## Step 1 — Provision the stateful dependencies

This guide doesn't ship the database. Recommended baselines:

- **Postgres**: `db.r6g.xlarge` (or equivalent) for production. Enable
  `track_io_timing`, set `shared_buffers ~= 25% RAM`, and create the
  extensions: `CREATE EXTENSION vector; CREATE EXTENSION pg_trgm; CREATE
  EXTENSION citext; CREATE EXTENSION "uuid-ossp";` (the Alembic migration
  creates these too, but managed providers sometimes restrict CREATE
  EXTENSION).
- **Redis**: 4 GB instance, eviction policy `allkeys-lru`, persistence off
  (queues + rate-limit + idempotency are all replayable).
- **S3 bucket** with versioning + server-side encryption. Lifecycle rule to
  move old `backups/` to Glacier after 30 days is a nice extra.

---

## Step 2 — Create the namespace and secrets

```bash
kubectl create namespace kortex

# Object storage credentials
kubectl -n kortex create secret generic kortex-s3 \
  --from-literal=accessKey=<S3_ACCESS_KEY> \
  --from-literal=secretKey=<S3_SECRET_KEY>

# JWT signing secret (32+ random bytes, base64)
kubectl -n kortex create secret generic kortex-jwt \
  --from-literal=secret=$(openssl rand -base64 32)

# Optional: LLM provider key(s) for agentic recall
kubectl -n kortex create secret generic kortex-llm \
  --from-literal=anthropic_api_key=<ANTHROPIC_KEY>
```

> Wiring provider keys into pod env is operator-specific — the simplest path
> is a `valueFrom.secretKeyRef` patch in your overlay. The Helm chart leaves
> these blank so deploys without LLM credentials still work.

---

## Step 3 — Apply the migrations

```bash
kubectl -n kortex run --rm -it migrate \
  --image=ghcr.io/anthropic/kortex-api:0.1.0 \
  --restart=Never \
  --env=KORTEX_DATABASE_URL=postgresql+asyncpg://... \
  --command -- alembic upgrade head
```

The job exits 0 on success. Re-running is idempotent.

---

## Step 4 — Install the Helm chart

### Option A: `helm install` with values flags

```bash
helm install kortex deploy/helm/kortex \
  --namespace kortex \
  --set postgres.url='postgresql+asyncpg://kortex:PASSWORD@pg.svc:5432/kortex' \
  --set redis.url='redis://redis.svc:6379/0' \
  --set s3.endpointUrl='https://s3.amazonaws.com' \
  --set s3.bucket='kortex-prod-attachments' \
  --set api.ingress.host='kortex.example.com' \
  --set api.ingress.tlsSecret='kortex-tls' \
  --set image.api.tag='0.1.0' \
  --set image.mcp.tag='0.1.0' \
  --set image.worker.tag='0.1.0'
```

### Option B: Kustomize overlays

Pre-baked overlays for `dev`, `staging`, `prod` live under `deploy/k8s/overlays/`.
Edit `valuesInline` with your values, then:

```bash
kubectl kustomize deploy/k8s/overlays/prod | kubectl apply -f -
```

### What's running after install

```bash
kubectl -n kortex get pods
# kortex-kortex-api-<hash>           Running
# kortex-kortex-mcp-<hash>           Running
# kortex-kortex-worker-<hash>        Running
# kortex-kortex-beat-<hash>          Running

kubectl -n kortex get svc
# kortex-kortex-api    ClusterIP   ...   8000/TCP
# kortex-kortex-mcp    ClusterIP   ...   8765/TCP
```

---

## Step 5 — Mint a production API key

```bash
kubectl -n kortex exec deploy/kortex-kortex-api -- kortex key create \
  --name production --scope project --scope-id <PROJECT_ID>
```

Save the printed `kx_...` — it's shown exactly once.

---

## Step 6 — Smoke-test the deploy

```bash
HOST=https://kortex.example.com
KEY=kx_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

curl -s "$HOST/livez"   # → OK
curl -s "$HOST/readyz"  # → OK

curl -s "$HOST/v1/memories" -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"scope_type":"project","scope_id":1,"body":"prod smoke memory"}'

curl -s "$HOST/v1/search/recall" -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"prod smoke"}'
```

---

## Step 7 — Run the loadtest gate

The M9 SLO is `recall p99 < 1.2s @ 50 RPS`. The bundled tool exits non-zero
when the budget is busted:

```bash
KORTEX_API_URL=https://kortex.example.com \
KORTEX_API_KEY=kx_... \
python scripts/bench_retrieval.py --rps 50 --duration 5m
```

If it fails: check the Retrieval Performance dashboard's phase breakdown.
The runbook at `docs/operators/runbooks.md#kortexrecallslow` walks the
triage tree.

---

## Step 8 — Wire observability

The chart sets `KORTEX_OTEL_ENABLED=true` on every pod and points it at
`otel-collector.observability:4317` by default. Override via
`--set observability.otelExporter=...`.

### Prometheus rules

```bash
kubectl -n monitoring apply -f deploy/observability/prometheus/rules.yaml
```

This installs four alert groups:

- `kortex.api.slos` — error rate + p99 latency
- `kortex.retrieval` — recall p99
- `kortex.embed` — embedding backlog
- `kortex.tenancy` — cross-org violations (critical)

### Grafana dashboards

Import six dashboards from `deploy/observability/grafana/dashboards/`:

1. `retrieval_performance.json` — recall + phase breakdown
2. `embedding_pipeline.json` — throughput + backlog
3. `decay_consolidation.json` — tier transitions
4. `tenancy_health.json` — violation counters + rate-limit blocks
5. `api_slos.json` — RPS / errors / latency
6. `db_health.json` — pool, slow queries

```bash
for f in deploy/observability/grafana/dashboards/*.json; do
  curl -s -u admin:$GRAFANA_PASSWORD \
    -H 'Content-Type: application/json' \
    https://grafana.example.com/api/dashboards/db \
    -d "{\"dashboard\": $(cat $f), \"overwrite\": true}"
done
```

---

## Step 9 — Verify backups

The `kortex-backup` CronJob runs daily at 02:15 UTC. To kick a one-shot
right after install:

```bash
kubectl -n kortex create job --from=cronjob/kortex-kortex-backup backup-now
kubectl -n kortex logs job/backup-now
# Confirm an object lands in s3://<bucket>/backups/kortex-<timestamp>.sql.gz
```

Test the restore path on a scratch DB at least once — your DR posture is
only as good as your last verified restore. The `docs/operators/backup.md`
page documents the exact restore steps.

---

## Step 10 — Tenancy regression test (recommended)

Before opening the API to real tenants, run the cross-org leak test against
your live cluster:

```bash
KORTEX_DATABASE_URL=postgresql+asyncpg://... \
uv run pytest tests/integration/test_tenancy_regression.py -v
```

A non-zero exit means somebody bypassed `BaseRepository.tenant_query()` —
freeze the release and investigate.

---

## Operations cheat-sheet

| Task | Command |
|---|---|
| Scale API | `kubectl -n kortex scale deploy/kortex-kortex-api --replicas=5` |
| Bounce a deployment | `kubectl -n kortex rollout restart deploy/kortex-kortex-api` |
| Watch HPA | `kubectl -n kortex get hpa -w` |
| Tail API logs | `kubectl -n kortex logs -f deploy/kortex-kortex-api` |
| Rotate an API key | `kortex key revoke <public-id>` then mint a new one |
| Force a decay tick | `kortex admin force-decay-tick` (superuser API key) |
| Force a consolidate tick | `kortex admin consolidate` |
| Reindex embeddings | `kortex admin reindex-embeddings` (clears `embedding`, `embed_pending` refills) |

For deeper procedures (DR, key compromise, hot-fix migrations) see
`docs/operators/`.

---

## Smaller deploys — Docker Compose

If Kubernetes is overkill for your workload, the `docker/compose.yaml`
production-grade variant runs on a single VM:

```bash
git clone https://github.com/anthropic/kortex-memory
cd kortex-memory
cp .env.example .env       # edit for production: real DB URL, S3 creds, JWT secret
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec api alembic upgrade head
docker compose -f docker/compose.yaml exec api kortex key create --name production
```

Caveats:

- Compose ships MinIO; for production replace `KORTEX_S3_ENDPOINT_URL` with
  your real S3 endpoint and remove the `minio` + `minio-init` services.
- No HPA, no NetworkPolicy, no backup CronJob. Bring your own monitoring +
  off-host backups.
- TLS: terminate at a reverse proxy (Caddy, Traefik, nginx) on the host.

---

## Upgrades

Kortex versions follow SemVer. Patch releases (`0.1.x`) are drop-in;
minor releases (`0.2.0`) may include Alembic migrations. The release
playbook:

1. Read the [CHANGELOG.md](CHANGELOG.md) for the target version.
2. Take a fresh `pg_dump` (`kubectl -n kortex create job --from=cronjob/kortex-kortex-backup pre-upgrade`).
3. `helm upgrade kortex deploy/helm/kortex --version <new>` — pods roll over.
4. Run `alembic upgrade head` from a pod of the new image (Helm does not
   auto-migrate; explicit step prevents partial upgrades).
5. Smoke-test (`/livez`, `/readyz`, one recall call).
6. Watch dashboards for 15 minutes — error rate, recall p99, embed backlog.

Rollback: `helm rollback kortex` plus a corresponding `alembic downgrade`
if the migration is reversible (most are — they're symmetric by policy).

---

## Where to go from here

- [docs/operators/scale.md](docs/operators/scale.md) — sizing + autoscaling deep dive
- [docs/operators/backup.md](docs/operators/backup.md) — RPO/RTO, restore drill
- [docs/operators/rotate-keys.md](docs/operators/rotate-keys.md) — API key lifecycle
- [docs/operators/runbooks.md](docs/operators/runbooks.md) — alert-by-alert triage
- [docs/architecture/overview.md](docs/architecture/overview.md) — why it's built this way

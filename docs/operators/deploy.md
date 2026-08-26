# Deploying Kortex

Two supported install paths: Helm chart (production) and Docker Compose (dev).

## Helm (production)

Prereqs:
- Kubernetes 1.28+
- Postgres 16 with `pgvector >= 0.7` and `pg_trgm` extensions
- Redis 7
- S3-compatible object storage
- `prometheus-adapter` + `metrics-server` if you want the API/worker HPAs

Bootstrap secrets:

```sh
kubectl create namespace kortex
kubectl -n kortex create secret generic kortex-s3 \
  --from-literal=accessKey=... --from-literal=secretKey=...
kubectl -n kortex create secret generic kortex-jwt \
  --from-literal=secret=$(openssl rand -base64 32)
```

Install:

```sh
helm install kortex deploy/helm/kortex \
  --namespace kortex \
  --set postgres.url=postgresql+asyncpg://kortex:...@pg.svc:5432/kortex \
  --set redis.url=redis://redis.svc:6379/0 \
  --set s3.endpointUrl=https://s3.amazonaws.com \
  --set s3.bucket=kortex-prod-attachments \
  --set api.ingress.host=kortex.example.com
```

The release exposes:
- `kortex-api` (`/v1/...`, `/livez`, `/readyz`, `/metrics`)
- `kortex-mcp` (`/sse`, `/messages/`)
- `kortex-worker` + `kortex-beat` deployments

Run migrations once after install:

```sh
kubectl -n kortex run --rm -it migrate \
  --image=ghcr.io/vedantnimbarte/kortex-api:main \
  --command -- alembic upgrade head
```

## Docker Compose (dev)

```sh
docker compose -f docker/compose.yaml up -d
make migrate
make seed
```

Compose includes `api`, `mcp` (port 8765), `worker`, `beat`, plus `postgres`,
`redis`, `minio`.

# Developer setup

## Prereqs

- Python 3.12 (only — not 3.11 or 3.13)
- `uv 0.4+`
- Docker (for the dev stack)

## First clone

```sh
git clone git@github.com:vedantnimbarte/kortex-memory.git
cd kortex-memory
uv sync
docker compose -f docker/compose.yaml up -d postgres redis minio
make migrate
make seed
```

## Run things

```sh
uv run kortex-api                 # FastAPI at :8000
uv run kortex-mcp stdio           # MCP over stdio
uv run kortex-mcp serve --port 8765   # MCP over SSE
uv run kortex-worker worker       # Celery worker
uv run kortex-worker beat         # Celery beat
```

## Tests

```sh
uv run pytest -m unit           # fast, process-local
uv run pytest -m integration    # spins up testcontainers (Postgres+Redis+MinIO)
uv run pytest                   # both
```

## Lint + type

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/
uv run python -m tools.ruff_plugins.tenant_check .
```

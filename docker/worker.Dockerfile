FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /usr/local/bin/uv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq5 libffi8 ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* /app/
COPY packages/kortex-core/pyproject.toml /app/packages/kortex-core/
COPY packages/kortex-api/pyproject.toml /app/packages/kortex-api/
COPY packages/kortex-mcp/pyproject.toml /app/packages/kortex-mcp/
COPY packages/kortex-cli/pyproject.toml /app/packages/kortex-cli/
COPY packages/kortex-worker/pyproject.toml /app/packages/kortex-worker/

COPY packages /app/packages
COPY alembic.ini /app/
COPY alembic /app/alembic

RUN uv sync --frozen --no-dev --package kortex-worker --extra full \
 || uv sync --no-dev --package kortex-worker --extra full

CMD ["uv", "run", "kortex-worker", "worker"]

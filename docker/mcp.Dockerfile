FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /usr/local/bin/uv

WORKDIR /app

# Same system dependencies as the API image — asyncpg, argon2, cryptography.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq5 libffi8 ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Workspace manifests first (layer cache).
COPY pyproject.toml uv.lock* /app/
COPY packages/kortex-core/pyproject.toml /app/packages/kortex-core/
COPY packages/kortex-api/pyproject.toml /app/packages/kortex-api/
COPY packages/kortex-mcp/pyproject.toml /app/packages/kortex-mcp/
COPY packages/kortex-cli/pyproject.toml /app/packages/kortex-cli/
COPY packages/kortex-worker/pyproject.toml /app/packages/kortex-worker/

COPY packages /app/packages
COPY alembic.ini /app/
COPY alembic /app/alembic

RUN uv sync --frozen --no-dev --package kortex-mcp || uv sync --no-dev --package kortex-mcp

EXPOSE 8765
# Defaults to the SSE server; pass `stdio` to run the stdio transport instead.
CMD ["uv", "run", "kortex-mcp", "serve", "--host", "0.0.0.0", "--port", "8765"]

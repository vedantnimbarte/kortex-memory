# Kortex all-in-one — Postgres + pgvector, Redis, API, MCP, worker and beat in
# one container, for evaluation and solo use.
#
#   docker run -p 8000:8000 -p 8765:8765 -v kortex-data:/data kortex/kortex:local
#
# NOT for production. Everything shares one failure domain, Postgres runs with
# trust auth on loopback, and there is no backup story. `deploy/helm/kortex` is
# the production path; docker/compose.yaml is the full local stack.
#
# Set KORTEX_EMBEDDED_SERVICES=0 to skip the bundled Postgres/Redis and point
# at external ones — that is what docker/compose.minimal.yaml does, reusing
# this same image.

FROM pgvector/pgvector:pg16

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /usr/local/bin/uv

# redis-server + supervisor are what make this a single container; the rest is
# the same build/runtime set the api and worker images need.
RUN apt-get update && apt-get install -y --no-install-recommends \
      redis-server supervisor \
      build-essential libpq5 libffi8 ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Debian bookworm ships Python 3.11; the workspace pins >=3.12,<3.13.
RUN uv python install 3.12

WORKDIR /app

# Manifests first so dependency layers cache independently of source changes.
COPY pyproject.toml uv.lock* /app/
COPY packages/kortex-core/pyproject.toml /app/packages/kortex-core/
COPY packages/kortex-api/pyproject.toml /app/packages/kortex-api/
COPY packages/kortex-mcp/pyproject.toml /app/packages/kortex-mcp/
COPY packages/kortex-cli/pyproject.toml /app/packages/kortex-cli/
COPY packages/kortex-worker/pyproject.toml /app/packages/kortex-worker/

COPY packages /app/packages
COPY alembic.ini /app/
COPY alembic /app/alembic

# `full` pulls the local embedding model stack — without it nothing embeds and
# recall silently degrades to BM25, which is not a working evaluation.
RUN uv sync --frozen --no-dev --all-packages --extra full --python 3.12 \
 || uv sync --no-dev --all-packages --extra full --python 3.12

COPY docker/local/supervisord.conf /etc/kortex/supervisord.conf
COPY docker/local/entrypoint.sh /usr/local/bin/kortex-entrypoint
RUN chmod +x /usr/local/bin/kortex-entrypoint

# Defaults that make the container self-contained. Everything is overridable.
ENV KORTEX_ENV=development \
    KORTEX_LOG_JSON=false \
    KORTEX_EMBEDDED_SERVICES=1 \
    KORTEX_DATA_DIR=/data \
    KORTEX_STORAGE_BACKEND=fs \
    KORTEX_FS_STORAGE_ROOT=/data/blobs \
    KORTEX_DATABASE_URL=postgresql+asyncpg://kortex:kortex@127.0.0.1:5432/kortex \
    KORTEX_REDIS_URL=redis://127.0.0.1:6379/0 \
    KORTEX_API_HOST=0.0.0.0 \
    KORTEX_API_PORT=8000

EXPOSE 8000 8765
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/readyz || exit 1

ENTRYPOINT ["/usr/local/bin/kortex-entrypoint"]

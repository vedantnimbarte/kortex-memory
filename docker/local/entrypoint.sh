#!/usr/bin/env bash
# Bring up the all-in-one container in dependency order, then hand off to
# supervisor.
#
# Ordering is done here rather than in supervisor because supervisor has no
# notion of "start B once A is ready", and the app processes genuinely cannot
# start before the database exists and the migrations have run. Postgres and
# Redis are started as daemons; supervisor owns the four Python processes.
#
# ponytail: if the bundled Postgres dies, nothing restarts it and the container
# is broken until it is restarted. Acceptable for an evaluation image where the
# container is the unit of restart; move them under supervisor if this ever
# needs to survive longer.
set -euo pipefail

DATA_DIR="${KORTEX_DATA_DIR:-/data}"
PGDATA_DIR="$DATA_DIR/pgdata"
BLOB_DIR="${KORTEX_FS_STORAGE_ROOT:-$DATA_DIR/blobs}"
EMBEDDED="${KORTEX_EMBEDDED_SERVICES:-1}"

log() { printf '[kortex] %s\n' "$*"; }

mkdir -p "$DATA_DIR" "$BLOB_DIR"

# A JWT secret generated once and persisted, so tokens survive a restart and
# nobody evaluates Kortex on the insecure built-in default.
SECRET_FILE="$DATA_DIR/jwt_secret"
if [ ! -s "$SECRET_FILE" ]; then
  head -c 48 /dev/urandom | base64 | tr -d '\n' > "$SECRET_FILE"
  chmod 600 "$SECRET_FILE"
  log "generated a persistent JWT secret at $SECRET_FILE"
fi
KORTEX_JWT_SECRET="$(cat "$SECRET_FILE")"
export KORTEX_JWT_SECRET

if [ "$EMBEDDED" = "1" ]; then
  mkdir -p "$PGDATA_DIR"
  chown -R postgres:postgres "$PGDATA_DIR"

  if [ ! -s "$PGDATA_DIR/PG_VERSION" ]; then
    log "initialising Postgres in $PGDATA_DIR"
    # trust auth is safe here only because Postgres listens on loopback inside
    # the container and the port is not published by default.
    su postgres -c "initdb -D '$PGDATA_DIR' --username=kortex --auth=trust --encoding=UTF8" >/dev/null
  fi

  log "starting Postgres"
  su postgres -c "pg_ctl -D '$PGDATA_DIR' -o '-c listen_addresses=127.0.0.1 -p 5432' -w -t 60 start"

  if ! su postgres -c "psql -U kortex -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='kortex'\"" | grep -q 1; then
    log "creating the kortex database"
    su postgres -c "createdb -U kortex kortex"
  fi
  su postgres -c "psql -U kortex -d kortex -c 'CREATE EXTENSION IF NOT EXISTS vector'" >/dev/null

  log "starting Redis"
  redis-server --daemonize yes --bind 127.0.0.1 --save '' --appendonly no
fi

log "applying migrations"
uv run --frozen --no-dev alembic upgrade head

if [ "${KORTEX_LOCAL_SEED:-0}" = "1" ]; then
  log "seeding demo data"
  uv run --frozen --no-dev python scripts/seed_dev.py || log "seed failed (continuing)"
fi

cat <<'BANNER'

  Kortex is starting.

    API      http://localhost:8000     (docs at /docs)
    MCP/SSE  http://localhost:8765/sse

  First run downloads the embedding model (~1.3 GB); until it finishes,
  memories stay `pending` and recall falls back to keyword search.
  Watch it with:  kortex admin ingest-status

  This image is for evaluation and solo use, not production.

BANNER

exec supervisord -c /etc/kortex/supervisord.conf -n

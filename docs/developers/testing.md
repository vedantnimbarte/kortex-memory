# Testing

We have three test classes:

- **Unit** (`tests/unit/`) — pure-Python, process-local, no containers. Fast.
- **Integration** (`tests/integration/`) — testcontainers spawn `pgvector/pgvector:pg16`, `redis:7-alpine`, `minio/minio`. Each fixture does its own migrations.
- **E2E** (`tests/e2e/`) — full stack; we run these against `docker compose` rather than testcontainers.

## Coverage gate

CI enforces `--fail-under=85`. Hot paths (retrieval, repos, services) should be over 90; surface-glue (routers, CLI) hovers at the gate.

## Conventions

- Async tests use `pytest-asyncio` in auto mode — no `@pytest.mark.asyncio` needed.
- Fixtures that mutate the DB use `session_scope()` so they commit on success.
- Integration tests should commit before any new session opens (`await session.commit()`); the `session` fixture is its own transaction.

## Adding a tenancy assertion

Anything that surfaces memories or attachments must be exercised by
`tests/integration/test_tenancy_regression.py`. New retrieval paths get a new
assertion there.

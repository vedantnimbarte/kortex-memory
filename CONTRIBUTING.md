# Contributing to Kortex Memory

Thanks for looking. Kortex is a memory layer for LLM agents — a bug here means
someone's agent silently forgets something, so correctness and observability
matter more than feature count.

## Getting set up

```bash
git clone git@github.com:vedantnimbarte/kortex-memory.git
cd kortex-memory
cp .env.example .env
uv sync --all-packages
make dev && make migrate && make seed
kortex doctor
```

Full walkthrough in [RUNNING_LOCALLY.md](RUNNING_LOCALLY.md). You need Python
3.12 (not 3.11, not 3.13), `uv`, and Docker.

## Before you open a PR

```bash
make lint          # ruff check + format --check
make type          # mypy strict
make test-unit     # fast, process-local
make test          # adds integration (needs Docker)
uv run python -m tools.ruff_plugins.tenant_check .
```

That last one is the tenancy chokepoint lint. It is not optional — see below.

## The rules that aren't negotiable

**Tenant isolation.** Every query against a tenant-bound model goes through
`BaseRepository.tenant_query()`. Raw `select(Memory)` inside a repository
module fails CI. If you genuinely need to bypass it, add `# tenancy: ok` with
a reason explaining why the ids are already tenant-resolved.

**Migrations are reviewed by hand.** They live in `alembic/versions/` named
`YYYYMMDD_000N_kkx000N_slug.py`. Anything touching `memories` gets tested
against a seeded database first — it is the largest table and a bad migration
on a memory store is not recoverable for users.

**Failures must be visible.** A `except: log.warning(...); return` that leaves
data in an unusable state is a bug, not error handling. If something can fail,
it needs a counter, a retry policy, and a way for an operator to see it.
`kortex doctor` and `/v1/admin/ingest-status` exist because of exactly that
class of bug.

**Tests come with the change.** Non-trivial logic lands with the smallest test
that fails if the logic breaks. Unit tests for pure logic, integration tests
(testcontainers) for anything touching Postgres.

## Style

- `ruff format` decides formatting; don't argue with it.
- mypy runs in strict mode. New code should not add `# type: ignore`.
- Comments explain *why*, not *what*. The code says what.
- One logical change per PR. A three-file diff someone actually reads beats a
  thirty-file diff they skim.

## Where to start

Open issues are grouped into milestones. Anything not marked `[HUMAN]` is
fair game; `[HUMAN]` ones need a decision from the maintainer first — ask
before building.

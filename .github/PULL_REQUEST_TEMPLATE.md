## What this changes

<!-- One paragraph. What was wrong, and what is different now. -->

## Why

<!-- The evidence: an issue, a failure you hit, a user report. If this
     implements a planned work unit, link it (Closes #N). -->

## Checklist

- [ ] `make lint` and `make type` pass
- [ ] `make test-unit` passes; `make test` if this touches the database
- [ ] `uv run python -m tools.ruff_plugins.tenant_check .` passes
- [ ] New logic has a test that fails without the change
- [ ] Migrations reviewed by hand and tested against seeded data
- [ ] `CHANGELOG.md` updated
- [ ] Docs updated in the same PR if user-facing

## What was verified, and what wasn't

<!-- Be specific about what you could not run locally. "Integration tests not
     run — no Docker" is useful; silence is not. -->

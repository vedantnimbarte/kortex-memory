# Releasing Kortex

The end-to-end checklist for cutting a tagged release. Pre-1.0 the surface is
moving fast — these steps catch the obvious foot-guns.

---

## 0. Decide the version

SemVer. For v0.1.0 (the first cut) skip patch-vs-minor discussion. After that:

- **Patch (0.1.x)** — bug fixes, doc fixes, dep bumps. No schema, no API contract change.
- **Minor (0.x.0)** — new features, additive API/schema. Backwards-compatible CLI/MCP.
- **Major (x.0.0)** — breaking changes. Pre-1.0 we may still do these in minors with loud notes.

---

## 1. Pre-flight checks (locally)

```bash
git switch main
git pull --ff-only
make lint
make type
make test-unit
make test-integration
uv run python -m tools.ruff_plugins.tenant_check .
```

Everything green. Coverage gate must clear 85%.

---

## 2. Bump versions

Five packages plus the chart. Bump in lockstep:

| File | Bump |
|---|---|
| `pyproject.toml` (root) | `version` |
| `packages/kortex-core/pyproject.toml` | `version` |
| `packages/kortex-api/pyproject.toml` | `version` |
| `packages/kortex-mcp/pyproject.toml` | `version` |
| `packages/kortex-cli/pyproject.toml` | `version` |
| `packages/kortex-worker/pyproject.toml` | `version` |
| `deploy/helm/kortex/Chart.yaml` | `version` **and** `appVersion` |
| `deploy/helm/kortex/values.yaml` | `image.*.tag` for api/mcp/worker |
| `packages/kortex-mcp/src/kortex_mcp/server.py` | `SERVER_VERSION` |
| `packages/kortex-mcp/src/kortex_mcp/__init__.py` | `__version__` |

Quick sanity: `grep -R '"0.1.0"' packages/ deploy/ --include='*.toml' --include='*.yaml' --include='*.py'`.

---

## 3. Update the CHANGELOG

`CHANGELOG.md` has an entry per version. Add the new version block at the top.
Group changes under: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`,
`Security`. Reference notable PRs by number when applicable.

The `release.yaml` workflow auto-extracts the entry under `## [<version>]` into
the GitHub Release body — keep the heading format stable.

---

## 4. Rebuild the lockfile

```bash
uv lock --upgrade-package kortex-core --upgrade-package kortex-api \
        --upgrade-package kortex-mcp --upgrade-package kortex-cli \
        --upgrade-package kortex-worker
git add uv.lock
```

Confirm `uv sync` from a clean tree still works.

---

## 5. Verify the migrations stack

```bash
docker compose -f docker/compose.yaml down -v
make dev
sleep 5
make migrate
make seed
uv run pytest tests/integration/test_tenancy_regression.py -v
```

If any migration is new, also run `alembic downgrade base` and re-`upgrade head`
to verify symmetry.

---

## 6. Commit + tag + push

```bash
git add -A
git commit -m "release: v<version>"
git tag -a v<version> -m "kortex v<version>"
git push origin main
git push origin v<version>
```

This triggers two workflows:

- **`.github/workflows/release.yaml`** — matrix-builds all 5 packages and
  publishes them to PyPI via trusted publishing. Then creates a GitHub Release
  whose body is the extracted CHANGELOG entry.
- **`.github/workflows/docker.yaml`** — builds `kortex-api`, `kortex-mcp`, and
  `kortex-worker` images and pushes to GHCR tagged `<version>` and `latest`.

Watch both runs go green before announcing.

---

## 7. Smoke-test the published artifacts

```bash
# PyPI
pip install --no-cache-dir kortex-cli==<version>
kortex --help

# GHCR
docker pull ghcr.io/anthropic/kortex-api:<version>
docker pull ghcr.io/anthropic/kortex-mcp:<version>
docker pull ghcr.io/anthropic/kortex-worker:<version>
```

If you maintain a docs site:

```bash
mkdocs gh-deploy --config-file docs/mkdocs.yml
```

---

## 8. Announce

Suggested template (paste into release notes / Slack / docs blog):

> **Kortex Memory v<version>** is out.
>
> _Highlights:_ (3 bullets, the most user-visible bits from the CHANGELOG)
>
> _Install:_ `pip install kortex-cli==<version>` — quickstart at
> [RUNNING_LOCALLY.md](RUNNING_LOCALLY.md), production guide at
> [DEPLOYMENT.md](DEPLOYMENT.md).

---

## After-action items

- File the next milestone's first ticket within 24h so momentum doesn't stall.
- If anything bit you in the pre-flight or smoke test, add a one-line entry to
  this file. The checklist gets better the more times it's used.

---

## Hot-fix releases (off the main branch)

If a critical bug needs to ship outside the normal cadence:

```bash
git switch -c hotfix/<version>
# fix the bug, add a regression test
make test
git commit -am "fix: <description>"
git tag v<version>
git push origin hotfix/<version>
git push origin v<version>
# open a PR to merge back to main
```

The release workflow keys off the tag, not the branch, so this works without
touching `main` first.

---

## Yanking a broken release

```bash
# PyPI (per-package)
twine yank kortex-cli==<bad-version>

# GHCR
gh api -X DELETE /orgs/anthropic/packages/container/kortex-api/versions/<id>

# GitHub Release
gh release delete v<bad-version> --cleanup-tag
```

Push a fixed `v<version+1>` immediately and document the issue in CHANGELOG.

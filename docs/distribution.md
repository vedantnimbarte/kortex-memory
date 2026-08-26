# Distribution runbook

The research is blunt about this: distribution, not product, is the binding
constraint. Kortex has more retrieval machinery than most of the field and
roughly none of its reach.

The manifests in this repository are the half that can be committed. The other
half — submitting, publishing, posting — needs an account and a human, so this
page is the checklist rather than a description of something already done.

**Nothing here is done yet.** Every box is unticked on purpose.

## What is already in the repo

| File | For |
|---|---|
| `server.json` | the official MCP registry |
| `glama.json` | Glama |
| `.claude-plugin/marketplace.json` | `/plugin marketplace add vedantnimbarte/kortex-memory` |
| `plugin/` | the Claude Code plugin: MCP server + the `kortex-memory` skill |
| `docs/integrations/*.md` | one guide per harness |

A test (`tests/unit/test_distribution_manifests.py`) keeps the versions and the
repository URL in step, so these do not quietly rot to the state of a release
ago.

## Do these in order

The order matters: two of the four directories want a package that already
exists somewhere public, so publishing comes first.

### 1. Publish the packages — [ ]

Neither client is on a registry yet, and the MCP registry will not accept a
package it cannot verify you own.

```bash
uv build --package kortex           # packages/kortex-sdk
uvx twine upload dist/*             # needs a PyPI token

cd packages/kortex-ts && npm publish --access public   # needs an npm token
```

Container images already publish to `ghcr.io/vedantnimbarte/kortex-*` on every
push to `main`, so `server.json` points at those and works today. **Make the
`kortex-mcp` package public in the GitHub package settings** — it defaults to
private, and a private image fails registry verification with a confusing
404.

### 2. Official MCP registry — [ ]

The one that feeds the others. `server.json` uses the
`io.github.vedantnimbarte/*` namespace, which is verified through GitHub OAuth
rather than DNS.

```bash
mcp-publisher login github
mcp-publisher publish
```

Bump `version` in `server.json` for each release; the registry rejects a
re-publish of a version it already has.

### 3. Glama — [ ]

Indexes GitHub directly. `glama.json` names the maintainer so the listing can
be claimed. Submit the repository at <https://glama.ai/mcp/servers> and claim
it with the GitHub account in `glama.json`.

### 4. Smithery — [ ]

**Deliberately not committed.** Smithery's container runtime expects the server
to answer MCP over HTTP in a specific shape, and Kortex's SSE transport has not
been tested against it. Shipping a `smithery.yaml` that claims a deployment
works when it has never been run would produce a broken listing, which is worse
than no listing.

Test it first, then commit the file:

```yaml
runtime: "container"
build:
  dockerfile: "docker/mcp.Dockerfile"
  dockerBuildPath: "."
startCommand:
  type: "http"
  configSchema:
    type: object
    required: ["KORTEX_API_KEY", "KORTEX_DATABASE_URL"]
    properties:
      KORTEX_API_KEY: { type: string }
      KORTEX_DATABASE_URL: { type: string }
```

There is a second problem to solve before this can work at all: Smithery runs
the container, and Kortex needs a Postgres it cannot provide. A hosted demo
instance, or a listing that documents self-hosting only, are the two honest
options.

### 5. mcp.so — [ ]

Mirrors the official registry, so step 2 usually covers it. Check the listing
appeared a day or two later, and submit directly at <https://mcp.so/submit> if
not.

### 6. Announce — [ ]

Not a directory, but the same job. Show HN, r/ClaudeAI, r/mcp. The exit gate
(#16) is what these feed, and it asks for ≥25 stars and ≥3 external installs
before Phase 2 work is justified.

Two notes on this from the research, both about honesty being the better
strategy here:

- **Position above the native memory tool, never against it.** Claude's own
  memory tool is the thing most people will compare this to. Kortex backs it
  (`docs/api/memory-tool.md`) rather than competing with it, and saying so is a
  stronger pitch than pretending the comparison does not exist.
- **Do not claim benchmark numbers that have not been re-run.** `#22` covers
  that, and it needs a live deployment. Publishing stale numbers to make a
  launch look better is the one mistake that cannot be walked back.

## Before any of it

Almost none of the above is worth doing while `#5` is open. Seven days of
actually using Kortex will change what the guides say, and a launch is a poor
moment to discover the setup friction a week of dogfooding would have surfaced
for free.

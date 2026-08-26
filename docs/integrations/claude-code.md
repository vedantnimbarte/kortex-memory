# Claude Code

Two ways in. The plugin is one command and configures itself; `kortex init` is
for a repo you also want a SessionStart hook and a project-scoped key in.

## The plugin

```
/plugin marketplace add vedantnimbarte/kortex-memory
/plugin install kortex-memory@kortex
```

Claude Code prompts for two values on enable:

| | |
|---|---|
| **Kortex MCP endpoint** | `http://localhost:8765/sse` for a local `make dev` stack, or your deployment's host on `:8765` |
| **Kortex API key** | a `kx_*` key from `kortex key create` — stored in the system keychain, not in `settings.json` |

The plugin ships the MCP server and a `kortex-memory` skill. The skill is the
half that matters: the MCP tools give Claude a memory, and the skill tells it
*when* to write to one. Without it you get a corpus of "fixed a typo" that
buries the three facts worth keeping.

The plugin uses the SSE transport, so the machine running Claude Code needs to
reach the MCP service but **not** the database.

## `kortex init` instead

Use this when you want the repo wired rather than the user:

```bash
kortex init claude-code
```

It finds or creates the Project scope for the current git repo, mints a
project-scoped API key, picks a transport (SSE if the MCP service answers,
stdio otherwise), writes `.mcp.json`, and verifies with a write→read canary.
Re-running is a no-op; `--dry-run` shows what it would do; anything it replaces
is backed up to `<name>.bak`.

It also installs a `SessionStart` hook:

```json
{ "hooks": { "SessionStart": [{ "hooks": [{ "type": "command", "command": "kortex hook session-start" }] }] } }
```

which injects the project's memories at the top of every new session, so Claude
starts with context instead of having to think to ask for it. `--no-hooks`
skips it.

`--global` writes `~/.claude.json` instead of the repo's `.mcp.json`, for a
machine-wide setup.

## By hand

```json
{
  "mcpServers": {
    "kortex": {
      "type": "sse",
      "url": "http://localhost:8765/sse",
      "headers": { "Authorization": "Bearer ${KORTEX_API_KEY}" }
    }
  }
}
```

`${VAR}` and `${VAR:-default}` expand in `.mcp.json`, so a key never has to be
committed. The stdio form is in the README if the machine has database access
and you would rather not run the MCP service.

## Checking it worked

`/mcp` lists `kortex` as connected. Then:

> what do we know about this project?

Claude calls `search_memory` or `recall`. If it does not, the tools are
connected but nothing has been written yet — say "remember that we chose X
because Y" and ask again.

## Troubleshooting

**`/mcp` shows kortex as failed.** With SSE, check the service is up:
`curl -i http://localhost:8765/sse` should hang open rather than 404. With
stdio, check `kortex-mcp` is on `PATH` and `KORTEX_DATABASE_URL` is set — the
stdio transport talks to Postgres directly and fails at startup without it.

**Connected but every call is unauthorized.** The key is org-scoped and starts
`kx_`. `kortex key create` mints one; `kortex auth whoami` says which org the
current profile is in.

**The session hook prints nothing.** It only injects memories that exist in the
project scope for the current git repo. `kortex memory list` shows what is
there.

**Tools appear but Claude never uses them.** That is a prompting problem, not a
wiring one — install the plugin for the `kortex-memory` skill, or tell Claude
explicitly to check its memory first.

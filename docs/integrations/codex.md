# Codex

```bash
kortex init codex
```

Codex differs from the other three harnesses in two ways that the command
handles for you, and that are worth knowing before you edit anything by hand.

**It is stdio only.** Codex has no remote-MCP form, so `kortex init codex`
always writes the stdio transport regardless of `--transport`. That means the
machine running Codex needs to reach the **database**, not just the MCP
service. Against a remote deployment that usually means a tunnel or a VPN.

**Its config is user-level, not per-repo.** There is no project-scoped Codex
config, so the entry lands in `~/.codex/config.toml` and applies everywhere.
The key it writes is still scoped to one project, so Codex sees that project's
memories in every repo you open. If you work across several projects, mint a
workspace-scoped key instead and pass `--workspace`.

## What it writes

```toml
[mcp_servers.kortex]
command = "kortex-mcp"
args = ["stdio"]
env = { KORTEX_API_KEY = "kx_...", KORTEX_DATABASE_URL = "postgresql+asyncpg://kortex:kortex@localhost:5432/kortex" }
```

The file is edited through `tomlkit`, so your comments and formatting survive
the merge and an existing `kortex` entry is replaced in place rather than
duplicated.

## Checking it worked

Start Codex and ask it to recall something you have written:

> what do we know about the ledger?

## Troubleshooting

**`kortex-mcp: command not found`.** stdio spawns the binary directly, so it has
to be on the `PATH` Codex inherits — which is not necessarily your shell's.
Point `command` at the absolute path from `which kortex-mcp` if in doubt.

**It starts and immediately exits.** Almost always `KORTEX_DATABASE_URL`: the
stdio transport connects to Postgres at startup and there is no fallback. Test
the DSN with `kortex doctor` first.

**Wrong project's memories.** The user-level config means one key for every
repo. `kortex init codex --workspace <slug>` mints a workspace-scoped key so
Codex sees the whole workspace instead of one project's slice.

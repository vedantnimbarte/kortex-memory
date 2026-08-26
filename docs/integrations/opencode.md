# OpenCode

```bash
kortex init opencode
```

Writes `opencode.json` in the current repo, or
`~/.config/opencode/opencode.json` with `--global`.

## By hand

OpenCode uses its own config shape rather than the `mcpServers` object the
other harnesses share — `mcp`, with an explicit `type` and an `enabled` flag:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kortex": {
      "type": "remote",
      "url": "http://localhost:8765/sse",
      "headers": { "Authorization": "Bearer kx_..." },
      "enabled": true
    }
  }
}
```

or local:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kortex": {
      "type": "local",
      "command": ["kortex-mcp", "stdio"],
      "environment": {
        "KORTEX_API_KEY": "kx_...",
        "KORTEX_DATABASE_URL": "postgresql+asyncpg://kortex:kortex@localhost:5432/kortex"
      },
      "enabled": true
    }
  }
}
```

Note `command` is a single array, not a `command` plus `args`, and the env key
is `environment`. `kortex init` writes the right one either way; these are the
two details to get right if you are editing by hand.

`kortex init` adds the `$schema` line if the file does not have one, and leaves
every other key alone.

## Checking it worked

Ask OpenCode something that needs memory:

> what did we decide about the ledger schema?

## Troubleshooting

**The server is configured but never used.** Check `enabled` is `true` — it is
explicit in OpenCode's config and a missing flag reads as off.

**Remote connects, tools fail.** The `Authorization` header has to be
`Bearer kx_...`. A bare key without the `Bearer` prefix authenticates as
anonymous and every scoped call then fails.

**Local exits at startup.** stdio needs `KORTEX_DATABASE_URL`; it talks to
Postgres directly. `kortex doctor` checks the DSN before you debug the harness.

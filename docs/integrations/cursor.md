# Cursor

```bash
kortex init cursor
```

Writes `.cursor/mcp.json` in the current repo, or `~/.cursor/mcp.json` with
`--global`. Same resolution as every harness: find or create the Project scope
for this git repo, mint a project-scoped key, probe for SSE and fall back to
stdio, then verify with a write→read canary.

## By hand

```json
{
  "mcpServers": {
    "kortex": {
      "type": "sse",
      "url": "http://localhost:8765/sse",
      "headers": { "Authorization": "Bearer kx_..." }
    }
  }
}
```

Cursor reads the same `mcpServers` shape as Claude Code, which is why one
merge function serves both. The stdio form works too:

```json
{
  "mcpServers": {
    "kortex": {
      "command": "kortex-mcp",
      "args": ["stdio"],
      "env": {
        "KORTEX_API_KEY": "kx_...",
        "KORTEX_DATABASE_URL": "postgresql+asyncpg://kortex:kortex@localhost:5432/kortex"
      }
    }
  }
}
```

Use stdio when the machine can reach Postgres and you would rather not run the
MCP service; use SSE when it cannot, which is the usual case against a remote
deployment.

## Two things specific to Cursor

**MCP tools only run in Agent mode.** In Ask or Edit mode the server connects
and is simply never called — which looks identical to a broken server. Check
the mode before debugging the config.

**Kortex adds 16 tools.** Cursor has historically capped how many tools it will
send to the model across all servers, so on a setup with several MCP servers
some of Kortex's can be silently dropped. If recall works but, say, linking
does not, disable a server you are not using and try again.

## Checking it worked

Settings → MCP shows `kortex` with its tools listed. Then, in Agent mode:

> check our memory for what we decided about the database

## Troubleshooting

**Server shows no tools.** Cursor caches the tool list; toggle the server off
and on in Settings → MCP.

**Works in one repo, not another.** `.cursor/mcp.json` is project-scoped. Run
`kortex init cursor` in the second repo — it gets its own Project scope and its
own key, which is the point rather than a limitation: memories do not leak
between unrelated repos.

**Unauthorized.** `kortex auth whoami` confirms which org the key belongs to.
Keys are org-scoped, so a key from another org authenticates fine and then
finds nothing.

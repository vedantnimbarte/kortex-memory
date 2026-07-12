# Quickstart

## 1. Install

Either pip:

```sh
pip install kortex-cli
```

…or from the workspace (for hacking):

```sh
git clone git@github.com:vedantnimbarte/kortex-memory.git
cd kortex-memory
uv sync
```

## 2. Run the stack locally

```sh
docker compose -f docker/compose.yaml up -d   # postgres + redis + minio + api + mcp + worker
make migrate
make seed
```

`make seed` prints the freshly-minted API key — save it.

## 3. Configure your shell

```sh
export KORTEX_API_URL=http://localhost:8000
export KORTEX_API_KEY=kx_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 4. Try it

```sh
kortex memory create --body "Use Redis with a 5min TTL for the search cache"
kortex search "caching strategy"
kortex recall "what did we decide about caching?" --synthesize
```

## 5. Wire Claude Code

Add to your Claude Code MCP config:

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

Restart Claude Code and your agent now has `remember`, `recall`,
`search_memory`, `attach_file`, `get_context_bundle`, and ten more tools.

# Backing Claude's memory tool

Anthropic's [memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
(`memory_20250818`) is client-side: Claude asks for a file operation, *your*
application performs it, and you hand back the result. Most implementations
write to local disk.

Local disk gives you one user, on one machine, in one tool, with no access
control and no audit trail. Point the same tool at a Kortex scope and the files
become ordinary memories — same review gating, same PII scanning, same trust
policy, visible to the MCP tools and the REST API and the console, shared
across a team, exportable, and soft-deleted rather than erased.

Nothing about the Claude side changes. Declare the tool exactly as documented:

```python
tools=[{"type": "memory_20250818", "name": "memory"}]
```

## With the Python SDK

```python
import anthropic
from kortex import Kortex

claude = anthropic.Anthropic()
kx = Kortex(scope=("project", 7))

messages = [{"role": "user", "content": "Help me with the ledger migration."}]

while True:
    response = claude.messages.create(
        model="claude-opus-5",
        max_tokens=16000,
        messages=messages,
        tools=[{"type": "memory_20250818", "name": "memory"}],
    )
    if response.stop_reason != "tool_use":
        break

    results = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "memory":
            answer = kx.memory_tool(block.input)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": answer.content,
                    "is_error": answer.is_error,
                }
            )
    messages += [
        {"role": "assistant", "content": response.content},
        {"role": "user", "content": results},
    ]
```

TypeScript is the same shape — `await kx.memoryTool(block.input)`, returning
`{ content, isError }`.

## Without an SDK

One endpoint, any language. Post the `tool_use` block's `input` verbatim:

```bash
curl -X POST "$KORTEX_API/v1/memory-tool" \
  -H "X-API-Key: $KORTEX_API_KEY" -H 'Content-Type: application/json' \
  -d '{
        "command": {"command": "view", "path": "/memories"},
        "scope_type": "project",
        "scope_id": 7
      }'
```

```json
{ "content": "Here're the files and directories up to 2 levels deep in /memories, …", "is_error": false }
```

Put `content` in the tool result and copy `is_error` onto the block.

The endpoint answers **200 even for a failed command**. That looks wrong and is
deliberate: a 404 for a missing file would be correct HTTP and useless, because
you have to turn it back into a string for Claude anyway. Claude recovers from
`The path /memories/x does not exist`; it cannot recover from an exception your
proxy swallowed. Genuine failures — unauthenticated, no such scope, database
down — still error normally.

## Where the files go

A memory-tool file is a memory whose `metadata.memory_tool_path` is its path and
whose title is that path. It is written with `source_type: tool_output`, so the
trust policy treats it as model-authored rather than human-authored.

Nothing is namespaced away from your other memories: a fact an agent wrote
through MCP and a file Claude wrote through its native tool land in the same
scope and are retrieved together. That is the point — one corpus, not two.

## Three deliberate differences from a filesystem

**A gated write says it was held.** If the project reviews writes, or the
content trips injection quarantine, `create` returns

```text
File created successfully at: /memories/notes.md — but it is held for human
review (project reviews every write) and will not be readable until approved.
```

A bare "created" would tell Claude it had saved something readable when it had
not, and the next session would find the file missing with nothing to explain
why. A held file still occupies its path, so `create` on it edits rather than
minting a second row at the same address — and `view` returns the held notice
rather than the content, because a review gate that hands the text straight
back to the model is decorative.

**`delete` is recoverable.** Retrieval stops; the row survives for export and
audit. "The agent deleted it" is something a compliance reviewer needs to be
able to see.

**`create` on an existing path overwrites.** Anthropic's reference errors
instead. Claude's own tool description says `create` "creates or overwrites", so
erroring makes it retry with delete-then-create — two more round trips for the
same outcome. The row keeps its id and its `updated_at` moves, so the change is
visible in the console.

## Security

Path validation is the implementer's responsibility and Anthropic says so.
Every command here is normalised and checked: anything outside `/memories`,
anything containing `..` or a backslash, and anything percent-encoded is
refused before it reaches the database.

Canonicalisation is not only a security measure. Without it
`/memories/a/../b` and `/memories/b` would be two different rows — Claude
writes to one, reads back the other, and its memory appears to have been lost
with nothing in any log to say why.

The usual advice applies on top: the memory tool writes what the conversation
contains, so a scope an agent writes to freely should not be one where a leak
would matter. Set `sensitivity` on the call to raise the classification of what
it stores, and turn on review gating for a project where an agent works with
material the whole org should not read back.

# lisa-pack-letta

Lisa Letta (MemGPT) integration pack — Letta as a memory provider and
stateful-agent peer.

The pack does two things:

1. **Memory provider.** It owns the generic `memory.add` / `memory.search` /
   `memory.list` aliases and persists durable facts as Letta archival
   memory passages for the Letta agent mapped to the Lisa identity.
2. **Stateful-agent peer.** It routes `/letta` and `/letta-agent` turns to a
   Letta agent that owns persistent memory blocks and archival memory across
   conversations.

## What it provides

| Layer | Path | Role |
| --- | --- | --- |
| Modes | `modes/letta/`, `modes/letta-agent/` | Chat delegation and the zero-model-call action path. |
| Operations | `operations/letta/` | Agent resolution, message send, archival search, core-memory update, sync, compaction. |
| MCP server | `mcp_memory_server.py` | The `lisa-letta-memory` adapter that translates the generic memory contract to the Letta REST API. |
| Slice provider | `slice_provider.py` | Pressure-driven Letta sync/compaction after each turn. |
| Host commands | `commands.py` | `/letta status`, `/letta agent`, `/letta sync`, `/letta compact`. |

### Operations

- **`letta_ensure_agent`** — resolve or create the Letta agent mapped to this
  Lisa identity. Idempotent.
- **`letta_send_message`** — send the user query to the mapped Letta agent
  and return its response verbatim.
- **`letta_search_archival`** — search the Letta agent's own archival plane.
  For normal recall use the generic `memory.search` alias instead.
- **`letta_update_core_memory`** — write high-salience durable context into
  the agent's in-context memory blocks (persona, project rules, profile).
- **`letta_sync_memory`** — push Lisa-distilled memories into Letta archival
  memory via the generic `memory.search` alias.
- **`letta_compact_agent`** — compact the mapped agent's context.

### Modes

- **`letta`** (chat, priority 8) — the model picks among the Letta
  operations and `recall_memory` based on the user's phrasing.
- **`letta-agent`** (action, priority 9) — runs `letta_ensure_agent` then
  `letta_send_message` and returns immediately, with **no Lisa model call**.
  The Letta agent's own model loop runs server-side.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `LETTA_BASE_URL` | `http://localhost:8283` | Letta server root. |
| `LETTA_API_KEY` | *(unset)* | API key for Letta Cloud. |
| `LETTA_DEFAULT_AGENT_NAME` | `lisa-agent` | Name used when creating an agent. |
| `LETTA_AGENT_ID` | *(unset)* | Use this agent id directly, skipping lookup and creation. |
| `LETTA_SYNC_ENABLED` | *(off)* | Opt in to the pressure-driven sync slice. |

Select the pack as the memory owner via session context:

```yaml
providers:
  capabilities:
    memory: lisa-pack-letta
```

## Installation

```bash
pip install lisa-pack-letta
```

The pack pulls in `lisa-harness-kernel` and `lisa-harness-sdk`.

## Development

```bash
uv run ruff format --check lisa_packs/letta
uv run ruff check lisa_packs/letta
uv run mypy lisa_packs/letta
uv run pytest -m "not live"
```

Run the checks from a sibling framework checkout so the shared
`[tool.ruff]` and `[tool.mypy]` settings apply; `pytest` runs from the pack
root so `pythonpath = ["."]` makes `lisa_packs.letta` importable.

## License

MIT.

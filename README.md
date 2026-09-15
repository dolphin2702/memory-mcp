# memory-mcp

[🇷🇺 Русская версия](README.ru.md)

MCP server that gives LLM clients (Open WebUI, Claude Desktop, Cursor,
custom bots) access to **per-user long-term memory** backed by SQLite.

## Features

- **7 tools** — save, search, list, get, delete memories
- **Per-user isolation** — each `user_id` is a separate namespace
- **SQLite** — single file, no server, no setup
- **HTTP (streamable) and SSE transports** — works with any MCP client
- **CORS enabled** — ready for browser-based clients

## Installation

### Docker (recommended)

```bash
docker pull ghcr.io/dolphin2702/memory-mcp:latest
```

Run with a local data directory:

```bash
docker run -d \
  --name memory-mcp \
  -p 8765:8765 \
  -v $(pwd)/data:/data \
  -e DB_PATH=/data/memory.db \
  ghcr.io/dolphin2702/memory-mcp:latest
```

### From source

```bash
git clone git@github.com:dolphin2702/memory-mcp.git
cd memory-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
DB_PATH=./data/memory.db memory-mcp
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/memory.db` | Path to the SQLite database file |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8765` | HTTP port |

## Tools

| Tool | Description |
|---|---|
| `add_memories` | Save a piece of information for a user |
| `search_memory` | Find memories by substring |
| `search_memories` | Alias for `search_memory` |
| `list_memories` | List all memories for a user |
| `get_memory` | Get a single memory by ID |
| `delete_memories` | Delete memories by a list of IDs |
| `delete_all_memories` | Delete all memories for a user |

Each tool accepts an optional `user_id` argument (defaults to `"default"`).
The server also reads the `X-User-Id` HTTP header if `user_id` is missing.

## User IDs

`user_id` is a free-form string. The convention is up to the client. Common
patterns:

- `alice` — one shared space per person
- `alice` and `alice_private` — two independent spaces (e.g. reference facts
  vs. personal notes)
- `telegram:471375444` — namespace per Telegram account

There is no built-in list of users; any string works.

## HTTP API

| Method | Path | Description |
|---|---|---|
| POST | `/mcp` | Streamable HTTP JSON-RPC |
| GET | `/sse` | SSE stream endpoint |
| POST | `/messages?sessionId=...` | SSE message channel |
| GET | `/health` | Liveness probe |
| GET | `/` | Status |
| POST | `/` | JSON-RPC (legacy) |

## Connecting from MCP clients

### Open WebUI

1. **Admin Settings → Integrations → Tool Servers**
2. **+ Add Connection**
3. Type: **MCP (Streamable HTTP)**
4. URL: `https://mem0.example.com/mcp`
5. Auth: none (or Bearer, if you've configured a reverse proxy)

### Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "memory": {
      "type": "streamable",
      "url": "https://mem0.example.com/mcp"
    }
  }
}
```

### curl

```bash
curl -s -X POST https://mem0.example.com/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"add_memories","arguments":{"text":"Alice prefers dark mode","user_id":"alice"}}}'
```

## Behind a reverse proxy (nginx)

SSE requires special settings. See the example configuration in the project
documentation. Minimum for `/sse`:

```nginx
proxy_buffering off;
proxy_read_timeout 24h;
proxy_set_header Connection '';
```

## License

MIT

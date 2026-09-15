# memory-mcp

[🇷🇺 Русская версия](README.ru.md)

MCP server providing per-user long-term memory backed by SQLite.

Full documentation coming in a future release. See [README.ru.md](README.ru.md).

## Quick start

docker pull ghcr.io/dolphin2702/memory-mcp:latest
docker run -d --name memory-mcp -p 8765:8765 -v ./data:/data ghcr.io/dolphin2702/memory-mcp:latest

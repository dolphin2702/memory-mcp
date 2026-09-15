# memory-mcp

[🇬🇧 English version](README.md)

MCP-сервер, дающий LLM-клиентам (Open WebUI, Claude Desktop, Cursor,
кастомные боты) доступ к **долговременной памяти по пользователям**.
Данные хранятся в SQLite.

## Возможности

- **7 инструментов** — сохранить, найти, показать, получить, удалить
- **Изоляция по `user_id`** — каждый пользователь в своём пространстве
- **SQLite** — один файл, никаких серверов и настройки
- **HTTP (streamable) и SSE транспорты** — работает с любым MCP-клиентом
- **CORS включён** — готов для браузерных клиентов

## Установка

### Docker (рекомендуется)

```bash
docker pull ghcr.io/dolphin2702/memory-mcp:latest
```

Запуск с локальной папкой для данных:

```bash
docker run -d \
  --name memory-mcp \
  -p 8765:8765 \
  -v $(pwd)/data:/data \
  -e DB_PATH=/data/memory.db \
  ghcr.io/dolphin2702/memory-mcp:latest
```

### Из исходников

```bash
git clone git@github.com:dolphin2702/memory-mcp.git
cd memory-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
DB_PATH=./data/memory.db memory-mcp
```

## Конфигурация

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DB_PATH` | `/data/memory.db` | Путь к файлу SQLite |
| `HOST` | `0.0.0.0` | Адрес прослушивания |
| `PORT` | `8765` | HTTP-порт |

## Инструменты

| Инструмент | Описание |
|---|---|
| `add_memories` | Сохранить факт |
| `search_memory` | Найти по подстроке |
| `search_memories` | Алиас для `search_memory` |
| `list_memories` | Список всех записей пользователя |
| `get_memory` | Одна запись по ID |
| `delete_memories` | Удалить по списку ID |
| `delete_all_memories` | Удалить все записи пользователя |

Каждый инструмент принимает необязательный аргумент `user_id` (по умолчанию
`"default"`). Если `user_id` не задан, сервер смотрит заголовок
`X-User-Id` HTTP-запроса.

## Про `user_id`

`user_id` — произвольная строка. Конвенция задаётся клиентом. Частые
паттерны:

- `alice` — одно общее пространство на человека
- `alice` и `alice_private` — два независимых пространства (например,
  справочные факты отдельно от личных заметок)
- `telegram:471375444` — namespace на конкретный Telegram-аккаунт

Списка пользователей нет — принимается любая строка.

## HTTP API

| Метод | Путь | Описание |
|---|---|---|
| POST | `/mcp` | Streamable HTTP JSON-RPC |
| GET | `/sse` | SSE-поток |
| POST | `/messages?sessionId=...` | Канал сообщений SSE |
| GET | `/health` | Проверка живости |
| GET | `/` | Статус |
| POST | `/` | JSON-RPC (legacy) |

## Подключение из MCP-клиентов

### Open WebUI

1. **Admin Settings → Integrations → Tool Servers**
2. **+ Add Connection**
3. Type: **MCP (Streamable HTTP)**
4. URL: `https://mem0.example.com/mcp`
5. Auth: none (или Bearer, если настроен на обратном прокси)

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
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"add_memories","arguments":{"text":"Алиса предпочитает тёмную тему","user_id":"alice"}}}'
```

## За обратным прокси (nginx)

Для SSE нужны особые настройки. Минимум для `/sse`:

```nginx
proxy_buffering off;
proxy_read_timeout 24h;
proxy_set_header Connection '';
```

## Лицензия

MIT

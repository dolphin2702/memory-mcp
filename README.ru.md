# memory-mcp

[🇬🇧 English version](README.md)

MCP-сервер долговременной памяти с разграничением по `user_id`, хранит данные в SQLite.

## Быстрый старт

```bash
docker pull ghcr.io/dolphin2702/memory-mcp:latest
docker run -d --name memory-mcp -p 8765:8765 -v ./data:/data ghcr.io/dolphin2702/memory-mcp:latest
```

## Инструменты

- `add_memories(text, user_id)` — сохранить факт
- `search_memory(query, user_id)` — найти по подстроке
- `search_memories(query, user_id)` — алиас
- `list_memories(user_id)` — все записи пользователя
- `get_memory(memory_id, user_id)` — одна запись по ID
- `delete_memories(memory_ids, user_id)` — удалить по списку ID
- `delete_all_memories(user_id)` — удалить всё у пользователя

## Разграничение по пользователям

`user_id` — произвольная строка. Конвенция задаётся клиентом. Пример для
семейного бота: `dmitry` и `dmitry_private` — два независимых пространства.

Если `user_id` не передан в аргументах, берётся из HTTP-заголовка `X-User-Id`,
иначе `"default"`.

## Конфигурация

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DB_PATH` | `/data/memory.db` | Путь к файлу SQLite |
| `HOST` | `0.0.0.0` | Адрес прослушивания |
| `PORT` | `8765` | HTTP-порт |

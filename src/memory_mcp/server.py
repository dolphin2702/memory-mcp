import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Dict, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/memory.db")


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        # Main table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON memories(user_id)")

        # Migration: add deleted_at column for soft delete
        cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
        if "deleted_at" not in cols:
            conn.execute("ALTER TABLE memories ADD COLUMN deleted_at INTEGER")
            logger.info("Migration: added deleted_at column")

        # Audit log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                action TEXT NOT NULL,
                user_id TEXT NOT NULL,
                memory_id TEXT,
                text TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("DB initialized at %s", DB_PATH)
    yield

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
)

sessions: Dict[str, asyncio.Queue] = {}


# ===================== AUDIT LOG =====================
def _log_audit(cur: sqlite3.Cursor, action: str, user_id: str,
               memory_id: Optional[str], text: Optional[str]) -> None:
    cur.execute(
        "INSERT INTO audit_log (timestamp, action, user_id, memory_id, text) VALUES (?, ?, ?, ?, ?)",
        (int(time.time()), action, user_id, memory_id, text),
    )


# ===================== ОСНОВНОЙ ЭНДПОИНТ ДЛЯ OPEN WEBUI =====================
@app.post("/mcp")
async def mcp_http_endpoint(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
            status_code=400,
        )

    logger.info(f"[HTTP MCP] Request: {body.get('method')} id={body.get('id')}")
    response = await process_request(body, request)
    return JSONResponse(response)


@app.get("/mcp")
async def mcp_get_endpoint():
    return JSONResponse({
        "status": "ok",
        "message": "MCP server is running. Use POST for JSON-RPC requests.",
    })


# ===================== SSE ЭНДПОИНТ =====================
@app.get("/sse")
async def sse_endpoint(request: Request):
    session_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    sessions[session_id] = queue

    async def event_generator():
        try:
            yield f"event: endpoint\ndata: /mcp\n\n"
            await asyncio.sleep(0.01)
            yield f"event: ping\ndata: {int(time.time())}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield message
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {int(time.time())}\n\n"
        finally:
            sessions.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Type",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/messages")
async def messages_endpoint(request: Request):
    session_id = request.query_params.get("sessionId")
    if not session_id or session_id not in sessions:
        logger.warning(f"Invalid or missing sessionId: {session_id}")
        return JSONResponse({"error": "Invalid or missing sessionId"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        logger.exception("Invalid JSON in messages endpoint")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    logger.info(f"[SSE] Received JSON-RPC request for session {session_id}: {body.get('method')}")
    response = await process_request(body, request)
    response_str = f"event: message\ndata: {json.dumps(response)}\n\n"
    if session_id in sessions:
        await sessions[session_id].put(response_str)

    return JSONResponse({"status": "accepted"})


# ===================== ВСПОМОГАТЕЛЬНЫЕ =====================
@app.get("/")
async def root_get():
    return JSONResponse({"status": "ok", "message": "MCP Memory Server is running"})


@app.post("/")
async def root_post(request: Request):
    body = await request.json()
    return JSONResponse(await process_request(body, request))


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connected")
    try:
        while True:
            data = await websocket.receive_text()
            try:
                req = json.loads(data)
                resp = await process_request(req)
                await websocket.send_text(json.dumps(resp, ensure_ascii=False))
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Invalid JSON"},
                }))
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")


# ===================== ОСНОВНАЯ ЛОГИКА =====================
async def process_request(body: dict, request: Optional[Request] = None) -> dict:
    method = body.get("method")
    req_id = body.get("id")

    if method == "initialize":
        from . import __version__
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memory-mcp", "version": __version__},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": req_id}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "add_memories",
                        "description": "Save a piece of information into long-term memory.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "description": "Text to remember"},
                                "user_id": {"type": "string", "default": "default"},
                            },
                            "required": ["text"],
                        },
                    },
                    {
                        "name": "search_memory",
                        "description": "Search memory by substring. Returns only active (non-deleted) records.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "user_id": {"type": "string", "default": "default"},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "search_memories",
                        "description": "Alias for search_memory.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "user_id": {"type": "string", "default": "default"},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "list_memories",
                        "description": "List all active memories for a user.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string", "default": "default"},
                            },
                        },
                    },
                    {
                        "name": "get_memory",
                        "description": "Get a single active memory by ID.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "memory_id": {"type": "string"},
                                "user_id": {"type": "string", "default": "default"},
                            },
                            "required": ["memory_id"],
                        },
                    },
                    {
                        "name": "delete_memories",
                        "description": "Soft-delete memories by IDs. Records can be restored later with restore_memories. Use only when the user explicitly asks to forget something.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "memory_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "user_id": {"type": "string", "default": "default"},
                            },
                            "required": ["memory_ids"],
                        },
                    },
                    {
                        "name": "delete_all_memories",
                        "description": "Soft-delete ALL memories for a user. Requires confirm=true. Records can be restored later with restore_memories.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string"},
                                "confirm": {
                                    "type": "boolean",
                                    "description": "Must be true to proceed",
                                },
                            },
                            "required": ["user_id", "confirm"],
                        },
                    },
                    {
                        "name": "memory_history",
                        "description": "Audit log: shows recent add/delete/restore actions for a user with full text.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string", "default": "default"},
                                "limit": {"type": "integer", "default": 50},
                            },
                        },
                    },
                    {
                        "name": "restore_memories",
                        "description": "Restore previously soft-deleted memories by ID.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "memory_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "user_id": {"type": "string", "default": "default"},
                            },
                            "required": ["memory_ids"],
                        },
                    },
                ]
            },
        }

    if method == "tools/call":
        try:
            tool_name = body["params"]["name"]
            args = body["params"]["arguments"]
        except KeyError:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Invalid params: missing name or arguments"},
            }

        user_id = args.get("user_id")
        if not user_id and request:
            user_id = request.headers.get("X-User-Id")
        if not user_id:
            user_id = "default"

        # Validate required args
        if tool_name == "add_memories" and "text" not in args:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing text"}}
        if tool_name in ("search_memory", "search_memories") and "query" not in args:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing query"}}
        if tool_name == "get_memory" and "memory_id" not in args:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing memory_id"}}
        if tool_name == "delete_memories" and "memory_ids" not in args:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing memory_ids"}}
        if tool_name == "restore_memories" and "memory_ids" not in args:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing memory_ids"}}
        if tool_name == "delete_all_memories" and not args.get("confirm"):
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "delete_all_memories requires confirm=true"}}

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            if tool_name == "add_memories":
                mem_id = str(uuid.uuid4())
                text = args["text"]
                cur.execute(
                    "INSERT INTO memories (id, text, user_id, created_at) VALUES (?, ?, ?, ?)",
                    (mem_id, text, user_id, int(time.time())),
                )
                _log_audit(cur, "add", user_id, mem_id, text)
                conn.commit()
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"✅ Сохранено (ID: {mem_id})"}]},
                }

            if tool_name in ("search_memory", "search_memories"):
                cur.execute(
                    "SELECT id, text FROM memories WHERE user_id = ? AND deleted_at IS NULL AND text LIKE ? ORDER BY created_at DESC LIMIT 5",
                    (user_id, f"%{args['query']}%"),
                )
                rows = cur.fetchall()
                text = "\n".join([f"[{r['id']}] {r['text']}" for r in rows]) if rows else "❌ Ничего не найдено"
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}]}}

            if tool_name == "list_memories":
                cur.execute(
                    "SELECT id, text, created_at FROM memories WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                    (user_id,),
                )
                rows = cur.fetchall()
                text = "\n".join([f"[{r['id']}] {r['text']} ({time.ctime(r['created_at'])})" for r in rows]) if rows else "❌ Нет воспоминаний"
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}]}}

            if tool_name == "get_memory":
                cur.execute(
                    "SELECT text, created_at FROM memories WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                    (args["memory_id"], user_id),
                )
                row = cur.fetchone()
                text = f"📝 {row['text']}\n📅 {time.ctime(row['created_at'])}" if row else "❌ Не найдено"
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}]}}

            if tool_name == "delete_memories":
                ids = args["memory_ids"]
                if not ids:
                    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "⚠️ Список пуст"}]}}
                placeholders = ",".join("?" * len(ids))
                # Fetch texts for audit before updating
                cur.execute(
                    f"SELECT id, text FROM memories WHERE id IN ({placeholders}) AND user_id = ? AND deleted_at IS NULL",
                    ids + [user_id],
                )
                to_delete = cur.fetchall()
                now = int(time.time())
                for row in to_delete:
                    cur.execute(
                        "UPDATE memories SET deleted_at = ? WHERE id = ? AND user_id = ?",
                        (now, row["id"], user_id),
                    )
                    _log_audit(cur, "delete", user_id, row["id"], row["text"])
                conn.commit()
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"🗑️ Помечено удалёнными: {len(to_delete)}. Восстановить: restore_memories(memory_ids=[...], user_id=\"{user_id}\")"}]},
                }

            if tool_name == "delete_all_memories":
                cur.execute(
                    "SELECT id, text FROM memories WHERE user_id = ? AND deleted_at IS NULL",
                    (user_id,),
                )
                rows = cur.fetchall()
                now = int(time.time())
                for row in rows:
                    cur.execute(
                        "UPDATE memories SET deleted_at = ? WHERE id = ? AND user_id = ?",
                        (now, row["id"], user_id),
                    )
                    _log_audit(cur, "delete", user_id, row["id"], row["text"])
                conn.commit()
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"🗑️ Помечено удалёнными: {len(rows)}. Восстановить: memory_history + restore_memories"}]},
                }

            if tool_name == "memory_history":
                limit = int(args.get("limit", 50))
                cur.execute(
                    "SELECT timestamp, action, memory_id, text FROM audit_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (user_id, limit),
                )
                rows = cur.fetchall()
                if not rows:
                    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "❌ История пуста"}]}}
                lines = []
                for r in rows:
                    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["timestamp"]))
                    action_icon = {"add": "➕", "delete": "🗑️", "restore": "♻️"}.get(r["action"], "•")
                    snippet = (r["text"] or "")[:80]
                    lines.append(f"{action_icon} [{ts}] {r['action']} [{r['memory_id'][:8] if r['memory_id'] else '?'}] {snippet}")
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "\n".join(lines)}]}}

            if tool_name == "restore_memories":
                ids = args["memory_ids"]
                if not ids:
                    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "⚠️ Список пуст"}]}}
                placeholders = ",".join("?" * len(ids))
                cur.execute(
                    f"SELECT id, text FROM memories WHERE id IN ({placeholders}) AND user_id = ? AND deleted_at IS NOT NULL",
                    ids + [user_id],
                )
                to_restore = cur.fetchall()
                for row in to_restore:
                    cur.execute(
                        "UPDATE memories SET deleted_at = NULL WHERE id = ? AND user_id = ?",
                        (row["id"], user_id),
                    )
                    _log_audit(cur, "restore", user_id, row["id"], row["text"])
                conn.commit()
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"♻️ Восстановлено: {len(to_restore)}"}]},
                }

            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}

        except sqlite3.Error as e:
            logger.exception("Database error")
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": f"Database error: {e}"}}
        finally:
            conn.close()

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

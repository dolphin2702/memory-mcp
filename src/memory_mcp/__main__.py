import os

import uvicorn


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(
        "memory_mcp.server:app",
        host=host,
        port=port,
        log_level="info",
        timeout_keep_alive=3600,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()

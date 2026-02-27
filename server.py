"""
Ephemeral WebSocket server — designed to run inside a GitHub Actions job
and be reached via a Cloudflare quick tunnel.

Endpoints
---------
GET  /          Health-check (plain text "OK")
GET  /clients   Number of currently connected WebSocket clients (JSON)
WS   /ws        WebSocket endpoint – broadcasts every incoming message
                to ALL connected clients (including the sender).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, JSONResponse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("km-server")


# ---------------------------------------------------------------------------
# Connection manager (broadcast to all connected sockets)
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    @property
    def count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        log.info("Client connected  (total=%d)", self.count)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        log.info("Client disconnected (total=%d)", self.count)

    async def broadcast(self, message: str, sender: Optional[WebSocket] = None) -> None:
        """Send *message* to every connected client."""
        dead: list[WebSocket] = []
        for connection in self._connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self._connections.remove(d)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Server starting up …")
    yield
    log.info("Server shutting down.")


app = FastAPI(
    title="Openterface KM Server",
    description="Ephemeral WebSocket server used via Cloudflare quick tunnel",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=PlainTextResponse)
async def health() -> str:
    return "OK"


@app.get("/clients")
async def client_count() -> JSONResponse:
    return JSONResponse({"connected_clients": manager.count})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            log.info("Message received: %r", data)
            await manager.broadcast(data, sender=ws)
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as exc:
        log.error("Unexpected error: %s", exc)
        manager.disconnect(ws)

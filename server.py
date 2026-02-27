"""
KeyMod – Ephemeral KM Server
==============================
Runs inside a GitHub Actions job and is reachable via a Cloudflare quick tunnel.
A browser user opens the web terminal and types; every keystroke is relayed in
real-time to the target PC via a lightweight agent (agent.py) that must be
running on the target machine.

Endpoints
---------
GET  /          Web terminal UI  (xterm.js)
GET  /status    Connected client counts  (JSON)
WS   /ws        Browser controller WebSocket
WS   /agent     Target-PC agent WebSocket

Message protocol
----------------
KeyMod Qt app → Server  (binary WebSocket frames, CH9329 wire format):
  [0x57][0xAB][addr][cmd][len][payload...][checksum]
  CMD 0x02 – keyboard  (8-byte HID report: modifier, 0x00, key×6)
  CMD 0x05 – relative mouse  (4 bytes: buttons, dx, dy, wheel)
  CMD 0x06 – absolute mouse  (7 bytes: buttons, x_lo, x_hi, y_lo, y_hi, wx, wy)

Browser web-terminal → Server  (JSON text frames):
  {"type": "key",         "data": "<char or escape sequence>"}
  {"type": "mouse_move",  "x": <int>, "y": <int>}
  {"type": "mouse_click", "x": <int>, "y": <int>, "button": "left"|"right"|"middle"}
  {"type": "mouse_scroll","x": <int>, "y": <int>, "dx": <int>, "dy": <int>}

Agent → Server → Browser  (back-channel):
  {"type": "ack", "msg": "..."}
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

# Path to the web UI template (templates/index.html)
_INDEX_HTML = Path(__file__).parent / "templates" / "index.html"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("keymod-server")


# ---------------------------------------------------------------------------
# Connection managers
# ---------------------------------------------------------------------------
class RoleManager:
    """Tracks two separate pools: browser controllers and PC agents."""

    def __init__(self) -> None:
        self._controllers: list[WebSocket] = []
        self._agents: list[WebSocket] = []

    # -- controllers (browsers) ------------------------------------------
    async def connect_controller(self, ws: WebSocket) -> None:
        await ws.accept()
        self._controllers.append(ws)
        log.info("Controller connected  (total=%d)", len(self._controllers))
        await self._broadcast_agent_status()

    async def disconnect_controller(self, ws: WebSocket) -> None:
        if ws in self._controllers:
            self._controllers.remove(ws)
        log.info("Controller disconnected (total=%d)", len(self._controllers))

    # -- agents (target PCs) ---------------------------------------------
    async def connect_agent(self, ws: WebSocket) -> None:
        await ws.accept()
        self._agents.append(ws)
        log.info("Agent connected  (total=%d)", len(self._agents))
        await self._broadcast_agent_status()

    async def disconnect_agent(self, ws: WebSocket) -> None:
        if ws in self._agents:
            self._agents.remove(ws)
        log.info("Agent disconnected (total=%d)", len(self._agents))
        await self._broadcast_agent_status()

    # -- relay & broadcast -----------------------------------------------
    async def relay_to_agents(self, message: str) -> None:
        dead: list[WebSocket] = []
        # Try to parse for better logging
        try:
            msg_obj = json.loads(message)
            msg_preview = f"type={msg_obj.get('type')} data={str(msg_obj.get('data', ''))[:50]}"
        except (json.JSONDecodeError, AttributeError):
            msg_preview = message[:100]
        
        if not self._agents:
            log.debug("No agents connected, message dropped: %s", msg_preview)
            return
        
        for agent in list(self._agents):
            try:
                await agent.send_text(message)
                log.debug("[→ AGENT] Sent: %s", msg_preview)
            except Exception as e:
                log.warning("Failed to send to agent: %s", e)
                dead.append(agent)
        for d in dead:
            if d in self._agents:
                self._agents.remove(d)
        
        if self._agents:
            log.info("→ Relayed to %d agent(s): %s", len(self._agents), msg_preview)

    async def relay_to_agents_bytes(self, data: bytes) -> None:
        """Relay a raw binary (CH9329) frame to every connected agent."""
        dead: list[WebSocket] = []
        # Parse CH9329 for better logging: [0x57][0xAB][addr][cmd][len]...
        frame_info = f"{len(data)} bytes: {data.hex(' ')[:60]}..."
        if len(data) >= 4 and data[0] == 0x57 and data[1] == 0xAB:
            cmd = data[3] if len(data) > 3 else 0
            cmd_names = {0x02: "KEYBOARD", 0x05: "MOUSE_REL", 0x06: "MOUSE_ABS"}
            frame_info = f"CH9329 {cmd_names.get(cmd, f'CMD_0x{cmd:02X}')} - {len(data)} bytes"
        
        if not self._agents:
            log.debug("No agents connected, binary frame dropped: %s", frame_info)
            return
        
        for agent in list(self._agents):
            try:
                await agent.send_bytes(data)
                log.debug("[→ AGENT] Sent binary: %s", frame_info)
            except Exception as e:
                log.warning("Failed to send binary to agent: %s", e)
                dead.append(agent)
        for d in dead:
            if d in self._agents:
                self._agents.remove(d)
        
        if self._agents:
            log.info("→ Relayed binary to %d agent(s): %s", len(self._agents), frame_info)

    async def relay_to_controllers(self, message: str) -> None:
        dead: list[WebSocket] = []
        # Try to parse for better logging
        try:
            msg_obj = json.loads(message)
            msg_preview = f"type={msg_obj.get('type')}"
        except (json.JSONDecodeError, AttributeError):
            msg_preview = message[:100]
        
        if not self._controllers:
            log.debug("No controllers connected, message dropped: %s", msg_preview)
            return
        
        for ctrl in list(self._controllers):
            try:
                await ctrl.send_text(message)
                log.debug("[← CTRL] Sent: %s", msg_preview)
            except Exception as e:
                log.warning("Failed to send to controller: %s", e)
                dead.append(ctrl)
        for d in dead:
            if d in self._controllers:
                self._controllers.remove(d)
        
        if self._controllers:
            log.info("← Relayed to %d controller(s): %s", len(self._controllers), msg_preview)

    async def _broadcast_agent_status(self) -> None:
        msg = json.dumps({"type": "agent_status", "count": len(self._agents)})
        await self.relay_to_controllers(msg)

    async def ping_all_controllers(self) -> None:
        """Send a keepalive ping to every controller so proxies don't time out."""
        msg = json.dumps({"type": "ping"})
        await self.relay_to_controllers(msg)

    @property
    def controller_count(self) -> int:
        return len(self._controllers)

    @property
    def agent_count(self) -> int:
        return len(self._agents)


manager = RoleManager()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("KeyMod server starting up …")

    async def _heartbeat() -> None:
        """Ping all browser clients every 20 s to keep proxy connections alive."""
        while True:
            await asyncio.sleep(20)
            await manager.ping_all_controllers()

    task = asyncio.create_task(_heartbeat())
    yield
    task.cancel()
    log.info("KeyMod server shutting down.")


app = FastAPI(
    title="KeyMod KM Server",
    description="Ephemeral WebSocket KM server – browser → server → agent",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def web_terminal() -> HTMLResponse:
    """Serve the web UI from templates/index.html."""
    return HTMLResponse(_INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/status")
async def status() -> JSONResponse:
    return JSONResponse({
        "controllers": manager.controller_count,
        "agents": manager.agent_count,
    })


@app.websocket("/ws")
async def controller_ws(ws: WebSocket) -> None:
    """KeyMod app (binary CH9329) or browser web-terminal (JSON) connection."""
    await manager.connect_controller(ws)
    try:
        while True:
            message = await ws.receive()

            # ---- Binary frame: CH9329 protocol from KeyMod app ----------
            if message.get("bytes"):
                raw_bytes: bytes = message["bytes"]
                log.info("[← BROWSER] Received binary frame: %d bytes", len(raw_bytes))
                await manager.relay_to_agents_bytes(raw_bytes)
                continue

            # ---- Text frame: JSON from browser web terminal -------------
            raw = message.get("text", "")
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "pong":
                log.debug("[← BROWSER] Received pong")
                continue  # browser replied to our keepalive – ignore

            if msg_type in ("key", "mouse_move", "mouse_click", "mouse_scroll"):
                log.info("[← BROWSER] Received %s: %s", msg_type, json.dumps(msg.get('data', msg))[:80])
                await manager.relay_to_agents(raw)

                # Echo printable chars back to the browser terminal display
                if msg_type == "key":
                    data = msg.get("data", "")
                    echo = json.dumps({"type": "echo", "data": data})
                    log.debug("[→ BROWSER] Sending echo: %s", data[:20])
                    await ws.send_text(echo)
            else:
                log.debug("[← BROWSER] Received unknown type: %s", msg_type)

    except WebSocketDisconnect:
        await manager.disconnect_controller(ws)
    except Exception as exc:
        log.error("Controller error: %s", exc)
        await manager.disconnect_controller(ws)


@app.websocket("/agent")
async def agent_ws(ws: WebSocket) -> None:
    """Target-PC agent connection."""
    await manager.connect_agent(ws)
    try:
        while True:
            message = await ws.receive()
            # Relay any back-channel message (ack, error, etc.) to controllers
            if message.get("text"):
                raw_text = message["text"]
                try:
                    msg_obj = json.loads(raw_text)
                    msg_type = msg_obj.get("type", "unknown")
                    log.info("[← AGENT] Received back-channel: %s", msg_type)
                except json.JSONDecodeError:
                    log.info("[← AGENT] Received back-channel: %s", raw_text[:80])
                await manager.relay_to_controllers(raw_text)
            elif message.get("bytes"):
                log.info("[← AGENT] Received binary back-channel: %d bytes", len(message["bytes"]))
    except WebSocketDisconnect:
        await manager.disconnect_agent(ws)
    except Exception as exc:
        log.error("Agent error: %s", exc)
        await manager.disconnect_agent(ws)

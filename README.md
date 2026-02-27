# KeyMod – Ephemeral Remote KM Server

A lightweight WebSocket server that lets you remotely control the keyboard and mouse of a target PC through a browser or a terminal client, routed through a temporary Cloudflare tunnel spun up inside a GitHub Actions job — no static server or open ports required.

---

## How it works

```
Browser / client_example.py
        │  WSS /ws  (JSON text frames)
        ▼
  KeyMod Server                ← runs in GitHub Actions + Cloudflare tunnel
    (server.py)
        │  WS /agent  (JSON or binary CH9329 frames)
        ▼
  agent.py                     ← runs on the target PC
        │  pynput
        ▼
  Target PC  keyboard / mouse
```

1. **GitHub Actions** starts `server.py` behind a Cloudflare quick-tunnel and prints the public URL in the job log.
2. **You** open the URL in a browser (web terminal UI) or run `client_example.py`.
3. **`agent.py`** runs on the machine you want to control and connects to `/agent`.
4. Every keystroke / mouse event typed in the browser is relayed in real-time to the agent, which replays it on the target PC using `pynput`.

---

## Repository layout

```
.
├── server.py               FastAPI WebSocket server
├── agent.py                Target-PC agent (run this on the machine to control)
├── client_example.py       Terminal keyboard client (alternative to the browser UI)
├── requirements.txt        Python dependencies
├── templates/
│   └── index.html          Web terminal UI (xterm.js)
└── .github/workflows/
    └── start-server.yml    GitHub Actions workflow
```

---

## Quick start

### 1 · Start the server via GitHub Actions

1. Go to **Actions → Start Ephemeral Server → Run workflow**.
2. Optionally set `duration_minutes` (1–60, default 10).
3. Watch the job log for the public URL, which looks like:

   ```
   PUBLIC HTTP URL : https://xxxx.trycloudflare.com
   PUBLIC WSS URL  : wss://xxxx.trycloudflare.com/ws
   ```

### 2 · Run the agent on the target PC

```bash
pip install websockets pynput

python agent.py wss://xxxx.trycloudflare.com
```

The agent reconnects automatically if the connection drops.

### 3 · Control from a browser

Open `https://xxxx.trycloudflare.com` in any browser. The xterm.js web terminal loads automatically. Once the agent connects, the **Agent ×1** badge turns green and every keystroke is forwarded to the target machine in real time.

### 3b · Control from the terminal (alternative)

```bash
pip install websockets

python client_example.py wss://xxxx.trycloudflare.com/ws
```

Every key you press is sent immediately — no Enter required. Press **Ctrl+Q** or **Ctrl+C** to quit.

---

## Running locally (development)

```bash
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

Then open `http://localhost:8000` in a browser, and run the agent pointing at `ws://localhost:8000`.

---

## Wire protocol

### Browser / client → Server (`/ws`)

JSON text frames:

| Type | Fields | Description |
|---|---|---|
| `key` | `data: str` | Keystroke or escape sequence (xterm.js format) |
| `mouse_move` | `x, y: int` | Move cursor to absolute pixel position |
| `mouse_click` | `x, y: int`, `button: "left"\|"right"\|"middle"` | Click at position |
| `mouse_scroll` | `x, y: int`, `dx, dy: int` | Scroll at position |
| `pong` | — | Reply to server keepalive `ping` |

The server also accepts **raw binary CH9329 frames** from native apps (e.g. the KeyMod Qt app):

```
[0x57][0xAB][addr][cmd][len][payload...][checksum]
```

| CMD | Description | Payload |
|---|---|---|
| `0x02` | Keyboard | 8-byte HID report: modifier, 0x00, key×6 |
| `0x05` | Relative mouse | buttons, dx, dy, wheel (signed bytes) |
| `0x06` | Absolute mouse | buttons, x\_lo, x\_hi, y\_lo, y\_hi, wx, wy |

### Server → Browser

| Type | Fields | Description |
|---|---|---|
| `echo` | `data: str` | Echo of the keystroke for local display |
| `agent_status` | `count: int` | Number of connected agents |
| `ping` | — | Keepalive (reply with `pong`) |

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web terminal UI |
| `GET` | `/status` | JSON: `{ "controllers": N, "agents": N }` |
| `WS` | `/ws` | Browser / client connection |
| `WS` | `/agent` | Target-PC agent connection |

---

## Dependencies

| Package | Used by |
|---|---|
| `fastapi` | Server |
| `uvicorn[standard]` | Server ASGI runner |
| `websockets` | Agent & client |
| `pynput` | Agent (keyboard/mouse input injection) |

Install all at once:
```bash
pip install -r requirements.txt
```

---

## Supported keys (agent)

- All printable characters and symbols
- Enter, Backspace, Tab, Escape, Space
- Arrow keys, Home, End, Page Up/Down, Delete
- F1–F12
- Ctrl+A through Ctrl+Z
- Modifier combos: Ctrl, Shift, Alt, Cmd (via CH9329 modifier byte)

> **macOS note:** `Insert` and `Num Lock` do not exist as pynput keys on macOS and are silently ignored.

---

## Security

This server is intentionally **ephemeral and unauthenticated** — it is designed to run for a short, controlled session inside a GitHub Actions job. Do **not** expose it permanently or on a public network without adding authentication.

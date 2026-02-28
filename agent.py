#!/usr/bin/env python3
"""
KeyMod Agent – runs on the **target PC**.

Connects to the KeyMod server's /agent WebSocket endpoint and executes
every keyboard / mouse command it receives using pynput.

Usage
-----
  pip install websockets pynput

  # Replace the URL with the Cloudflare tunnel URL printed by the GitHub Actions job:
  python agent.py wss://xxxx.trycloudflare.com

  # Or for a local server:
  python agent.py ws://localhost:8000

Press Ctrl-C to stop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import struct
import subprocess
import sys

import base64
import io

import websockets
from pynput.keyboard import Controller as KbController, Key, KeyCode
from pynput.mouse import Controller as MouseController, Button

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("keymod-agent")

# ---------------------------------------------------------------------------
# Screen resolution (used to map CH9329 absolute mouse coords to pixels)
# ---------------------------------------------------------------------------
try:
    import tkinter as _tk
    _root = _tk.Tk()
    _root.withdraw()
    SCREEN_W: int = _root.winfo_screenwidth()
    SCREEN_H: int = _root.winfo_screenheight()
    _root.destroy()
    del _root, _tk
except Exception:
    SCREEN_W, SCREEN_H = 1920, 1080
log.info("Screen resolution: %dx%d", SCREEN_W, SCREEN_H)

# ---------------------------------------------------------------------------
# CH9329 frame constants
# ---------------------------------------------------------------------------
CH9329_HEADER   = b"\x57\xAB"
CMD_KEYBOARD    = 0x02
CMD_MOUSE_REL   = 0x05
CMD_MOUSE_ABS   = 0x06
CH9329_MIN_LEN  = 6          # header(2) + addr(1) + cmd(1) + len(1) + chk(1)

# ---------------------------------------------------------------------------
# CH9329 modifier bitmask → pynput Key
# ---------------------------------------------------------------------------
MODIFIER_BITS: list[tuple[int, Key]] = [
    (0x01, Key.ctrl_l),
    (0x02, Key.shift),
    (0x04, Key.alt),
    (0x08, Key.cmd),
    (0x10, Key.ctrl_r),
    (0x20, Key.shift_r),
    (0x40, getattr(Key, "alt_r", Key.alt_gr)),
    (0x80, getattr(Key, "cmd_r",  Key.cmd)),
]

# ---------------------------------------------------------------------------
# HID usage-ID → pynput Key / KeyCode
# ---------------------------------------------------------------------------
def _kc(ch: str) -> KeyCode:
    return KeyCode.from_char(ch)

def _k(name: str) -> Key | None:
    """Return Key.<name> if it exists on this platform, else None (silently skipped)."""
    return getattr(Key, name, None)

_raw_hid: dict[int, Key | KeyCode | None] = {
    # a – z
    **{0x04 + i: _kc(chr(ord('a') + i)) for i in range(26)},
    # 1 – 9, 0
    **{0x1E + i: _kc(str(i + 1)) for i in range(9)},
    0x27: _kc('0'),
    # control / editing
    0x28: Key.enter,       0x29: Key.esc,         0x2A: Key.backspace,
    0x2B: Key.tab,         0x2C: _kc(' '),
    # punctuation
    0x2D: _kc('-'),        0x2E: _kc('='),
    0x2F: _kc('['),        0x30: _kc(']'),        0x31: _kc('\\'),
    0x33: _kc(';'),        0x34: _kc("'"),        0x35: _kc('`'),
    0x36: _kc(','),        0x37: _kc('.'),        0x38: _kc('/'),
    # locking
    0x39: Key.caps_lock,
    # function keys
    0x3A: Key.f1,  0x3B: Key.f2,  0x3C: Key.f3,  0x3D: Key.f4,
    0x3E: Key.f5,  0x3F: Key.f6,  0x40: Key.f7,  0x41: Key.f8,
    0x42: Key.f9,  0x43: Key.f10, 0x44: Key.f11, 0x45: Key.f12,
    # navigation cluster (insert/num_lock absent on macOS – skipped via _k())
    0x49: _k('insert'),  0x4A: Key.home,     0x4B: Key.page_up,
    0x4C: Key.delete,    0x4D: Key.end,      0x4E: Key.page_down,
    0x4F: Key.right,     0x50: Key.left,     0x51: Key.down,  0x52: Key.up,
    # numpad
    0x53: _k('num_lock'),
    0x54: _kc('/'),  0x55: _kc('*'),  0x56: _kc('-'),  0x57: _kc('+'),
    0x58: Key.enter,
    0x59: Key.end,      0x5A: Key.down,  0x5B: Key.page_down,
    0x5C: Key.left,     0x5E: Key.right,
    0x5F: Key.home,     0x60: Key.up,    0x61: Key.page_up,
    0x62: _k('insert'), 0x63: Key.delete,
}
# Strip entries whose key constant is unavailable on this platform
HID_KEY: dict[int, Key | KeyCode] = {k: v for k, v in _raw_hid.items() if v is not None}

# Mouse button bitmask (CH9329) → pynput Button
MOUSE_BITS: list[tuple[int, Button]] = [
    (0x01, Button.left),
    (0x02, Button.right),
    (0x04, Button.middle),
]

# ---------------------------------------------------------------------------
# xterm.js escape-sequence → pynput Key mapping
# ---------------------------------------------------------------------------
ESCAPE_KEY_MAP: dict[str, Key] = {
    # Cursor keys
    "\x1b[A": Key.up,
    "\x1b[B": Key.down,
    "\x1b[C": Key.right,
    "\x1b[D": Key.left,
    # Home / End
    "\x1b[H": Key.home,
    "\x1b[F": Key.end,
    "\x1bOH": Key.home,
    "\x1bOF": Key.end,
    # Page Up / Down
    "\x1b[5~": Key.page_up,
    "\x1b[6~": Key.page_down,
    # Insert / Delete  (Key.insert not available on all platforms – skip safely)
    **({"\x1b[2~": Key.insert} if hasattr(Key, "insert") else {}),
    "\x1b[3~": Key.delete,
    # Function keys
    "\x1bOP":   Key.f1,
    "\x1bOQ":   Key.f2,
    "\x1bOR":   Key.f3,
    "\x1bOS":   Key.f4,
    "\x1b[15~": Key.f5,
    "\x1b[17~": Key.f6,
    "\x1b[18~": Key.f7,
    "\x1b[19~": Key.f8,
    "\x1b[20~": Key.f9,
    "\x1b[21~": Key.f10,
    "\x1b[23~": Key.f11,
    "\x1b[24~": Key.f12,
}

# Single-character control codes
CTRL_KEY_MAP: dict[str, Key] = {
    "\r":   Key.enter,
    "\n":   Key.enter,
    "\x7f": Key.backspace,
    "\x08": Key.backspace,
    "\t":   Key.tab,
    "\x1b": Key.esc,
}

# Mouse button name → pynput Button
BUTTON_MAP: dict[str, Button] = {
    "left":   Button.left,
    "right":  Button.right,
    "middle": Button.middle,
}

# ---------------------------------------------------------------------------
# Input controllers + state
# ---------------------------------------------------------------------------
keyboard = KbController()
mouse    = MouseController()

_kb_modifiers: int       = 0    # current CH9329 modifier bitmask
_kb_keys:      set[int]  = set() # current pressed HID keycodes
_mouse_buttons: int      = 0    # current CH9329 button bitmask


# ---------------------------------------------------------------------------
# CH9329 frame parser
# ---------------------------------------------------------------------------
def _ch9329_checksum(frame: bytes) -> int:
    """Sum of bytes addr..payload (frame[2:-1]) mod 256."""
    return sum(frame[2:-1]) & 0xFF


def parse_ch9329(data: bytes) -> tuple[int, bytes] | None:
    """
    Parse a CH9329 frame.  Returns (cmd, payload) or None if invalid.
    Frame: [0x57][0xAB][addr][cmd][len][payload...][checksum]
    """
    if len(data) < CH9329_MIN_LEN:
        return None
    if data[:2] != CH9329_HEADER:
        return None
    cmd     = data[3]
    length  = data[4]
    if len(data) < 5 + length + 1:
        return None
    payload  = data[5 : 5 + length]
    checksum = data[5 + length]
    if _ch9329_checksum(data[:5 + length + 1]) != checksum:
        log.warning("CH9329 checksum mismatch – frame ignored")
        return None
    return cmd, payload


# ---------------------------------------------------------------------------
# CH9329 executors
# ---------------------------------------------------------------------------
def execute_keyboard(payload: bytes) -> None:
    """Execute a CH9329 CMD_KEYBOARD (0x02) 8-byte HID report."""
    global _kb_modifiers, _kb_keys

    if len(payload) < 8:
        return

    new_mod  = payload[0]
    new_keys = {kc for kc in payload[2:8] if kc != 0x00}

    # --- release disappeared modifier bits ---
    for bit, key in MODIFIER_BITS:
        if (_kb_modifiers & bit) and not (new_mod & bit):
            try:
                keyboard.release(key)
            except Exception:
                pass

    # --- press new modifier bits ---
    for bit, key in MODIFIER_BITS:
        if (new_mod & bit) and not (_kb_modifiers & bit):
            try:
                keyboard.press(key)
            except Exception:
                pass

    # --- release disappeared keys ---
    for kc in _kb_keys - new_keys:
        pkey = HID_KEY.get(kc)
        if pkey:
            try:
                keyboard.release(pkey)
            except Exception:
                pass

    # --- press new keys ---
    for kc in new_keys - _kb_keys:
        pkey = HID_KEY.get(kc)
        if pkey:
            try:
                keyboard.press(pkey)
            except Exception:
                pass

    _kb_modifiers = new_mod
    _kb_keys      = new_keys
    log.debug("Keyboard: mod=0x%02x keys=%s", new_mod, [hex(k) for k in new_keys])


def execute_mouse_rel(payload: bytes) -> None:
    """Execute a CH9329 CMD_MOUSE_REL (0x05) relative-mouse report."""
    global _mouse_buttons

    if len(payload) < 4:
        return

    new_btns = payload[0]
    dx  = struct.unpack_from('b', payload, 1)[0]
    dy  = struct.unpack_from('b', payload, 2)[0]
    whl = struct.unpack_from('b', payload, 3)[0]

    # button state changes
    for bit, btn in MOUSE_BITS:
        if (new_btns & bit) and not (_mouse_buttons & bit):
            mouse.press(btn)
        elif not (new_btns & bit) and (_mouse_buttons & bit):
            mouse.release(btn)
    _mouse_buttons = new_btns

    if dx or dy:
        mouse.move(dx, dy)
    if whl:
        mouse.scroll(0, whl)
    log.debug("Mouse rel: btns=0x%02x dx=%d dy=%d whl=%d", new_btns, dx, dy, whl)


def execute_mouse_abs(payload: bytes) -> None:
    """Execute a CH9329 CMD_MOUSE_ABS (0x06) absolute-mouse report."""
    global _mouse_buttons

    if len(payload) < 7:
        return

    new_btns  = payload[0]
    x_raw     = struct.unpack_from('<H', payload, 1)[0]   # 0x0000 – 0x7FFF
    y_raw     = struct.unpack_from('<H', payload, 3)[0]
    whl       = struct.unpack_from('b',  payload, 5)[0]

    x_px = int(x_raw / 0x7FFF * SCREEN_W)
    y_px = int(y_raw / 0x7FFF * SCREEN_H)

    # button state changes
    for bit, btn in MOUSE_BITS:
        if (new_btns & bit) and not (_mouse_buttons & bit):
            mouse.press(btn)
        elif not (new_btns & bit) and (_mouse_buttons & bit):
            mouse.release(btn)
    _mouse_buttons = new_btns

    mouse.position = (x_px, y_px)
    if whl:
        mouse.scroll(0, whl)
    log.debug("Mouse abs: btns=0x%02x pos=(%d,%d) whl=%d", new_btns, x_px, y_px, whl)


def dispatch_ch9329(data: bytes) -> None:
    """Parse and execute a raw CH9329 binary frame."""
    result = parse_ch9329(data)
    if result is None:
        log.warning("Invalid / malformed CH9329 frame (%d bytes) – ignored", len(data))
        return
    cmd, payload = result
    if cmd == CMD_KEYBOARD:
        execute_keyboard(payload)
    elif cmd == CMD_MOUSE_REL:
        execute_mouse_rel(payload)
    elif cmd == CMD_MOUSE_ABS:
        execute_mouse_abs(payload)
    else:
        log.debug("Unknown CH9329 cmd 0x%02x – ignored", cmd)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def handle_key(data: str) -> None:
    """Translate an xterm.js key sequence and send it via pynput."""
    # Multi-char escape sequence → mapped special key
    if data in ESCAPE_KEY_MAP:
        keyboard.press(ESCAPE_KEY_MAP[data])
        keyboard.release(ESCAPE_KEY_MAP[data])
        log.debug("Special key: %r", data)
        return

    # Single-char control codes
    if data in CTRL_KEY_MAP:
        keyboard.press(CTRL_KEY_MAP[data])
        keyboard.release(CTRL_KEY_MAP[data])
        log.debug("Control key: %r", data)
        return

    # Ctrl+A … Ctrl+Z  (\x01 … \x1a, excluding already-handled codes)
    if len(data) == 1 and "\x01" <= data <= "\x1a":
        letter = chr(ord(data) + ord("a") - 1)
        with keyboard.pressed(Key.ctrl):
            keyboard.press(letter)
            keyboard.release(letter)
        log.debug("Ctrl+%s", letter.upper())
        return

    # Printable / multi-char text (paste etc.)
    keyboard.type(data)
    log.debug("Typed: %r", data)


def handle_mouse_move(x: int, y: int) -> None:
    mouse.position = (x, y)
    log.debug("Mouse move → (%d, %d)", x, y)


def handle_mouse_click(x: int, y: int, button_name: str) -> None:
    btn = BUTTON_MAP.get(button_name, Button.left)
    mouse.position = (x, y)
    mouse.click(btn)
    log.debug("Mouse click %s @ (%d, %d)", button_name, x, y)


def handle_mouse_scroll(x: int, y: int, dx: int, dy: int) -> None:
    mouse.position = (x, y)
    mouse.scroll(dx, dy)
    log.debug("Mouse scroll (%d, %d) @ (%d, %d)", dx, dy, x, y)


# ---------------------------------------------------------------------------
# Hotkey combos (System tab quick-keys)
# Keys shared across multiple OS entries are intentional aliases.
# ---------------------------------------------------------------------------
HOTKEY_MAP: dict[str, list] = {
    # ── Windows ─────────────────────────────────────────────────────────
    "win":              [Key.cmd],
    "win+d":            [Key.cmd, "d"],
    "win+r":            [Key.cmd, "r"],
    "win+l":            [Key.cmd, "l"],
    "win+e":            [Key.cmd, "e"],
    "win+tab":          [Key.cmd, Key.tab],
    "alt+f4":           [Key.alt, Key.f4],
    "ctrl+alt+del":     [Key.ctrl, Key.alt, Key.delete],
    # ── macOS ────────────────────────────────────────────────────────────
    "cmd+space":        [Key.cmd, Key.space],
    "cmd+tab":          [Key.cmd, Key.tab],
    "cmd+q":            [Key.cmd, "q"],
    "cmd+h":            [Key.cmd, "h"],
    "cmd+m":            [Key.cmd, "m"],
    "cmd+w":            [Key.cmd, "w"],
    "ctrl+cmd+q":       [Key.ctrl, Key.cmd, "q"],
    "cmd+opt+esc":      [Key.cmd, Key.alt, Key.esc],
    # ── Linux ────────────────────────────────────────────────────────────
    "super":            [Key.cmd],
    "super+d":          [Key.cmd, "d"],
    "ctrl+alt+t":       [Key.ctrl, Key.alt, "t"],
    "ctrl+alt+l":       [Key.ctrl, Key.alt, "l"],
    "alt+tab":          [Key.alt, Key.tab],
    **( {"prtsc": [getattr(Key, "print_screen")]} if hasattr(Key, "print_screen") else {} ),
}


async def capture_and_send_screenshot(ws) -> None:
    """Capture the full screen and send it back as a base64 JPEG over the agent WS."""
    try:
        img = None
        try:
            import mss                                           # type: ignore
            from PIL import Image                               # type: ignore
            with mss.mss() as sct:
                raw = sct.grab(sct.monitors[0])                 # all monitors combined
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except ImportError:
            from PIL import ImageGrab                           # type: ignore
            img = ImageGrab.grab()

        if img is None:
            raise RuntimeError("No screenshot backend available")

        # Downscale to max 1280 px wide to keep payload manageable
        max_w = 1280
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        b64 = base64.b64encode(buf.getvalue()).decode()
        await ws.send(json.dumps({
            "type": "screenshot",
            "data": f"data:image/jpeg;base64,{b64}",
            "width": img.width,
            "height": img.height,
        }))
        log.info("Screenshot sent (%d\u00d7%d, %.1f KB)", img.width, img.height, len(b64) * 0.75 / 1024)
    except Exception as exc:
        log.warning("Screenshot failed: %s", exc)
        try:
            await ws.send(json.dumps({"type": "screenshot_error", "error": str(exc)}))
        except Exception:
            pass


def handle_hotkey(combo: str) -> None:
    keys = HOTKEY_MAP.get(combo.lower())
    if not keys:
        log.warning("Unknown hotkey combo: %r", combo)
        return
    try:
        pressed = []
        for k in keys:
            keyboard.press(k)
            pressed.append(k)
        for k in reversed(pressed):
            keyboard.release(k)
        log.debug("Hotkey: %s", combo)
    except Exception as exc:
        log.warning("Hotkey error (%s): %s", combo, exc)


# ---------------------------------------------------------------------------
# Active window title (back-channel to browser)
# ---------------------------------------------------------------------------
def get_active_window_title() -> str:
    """Return the title of the foreground window, or empty string on failure."""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        elif system == "Darwin":
            script = 'tell application "System Events" to get name of first process whose frontmost is true'
            result = subprocess.run(["osascript", "-e", script],
                                    capture_output=True, text=True, timeout=2)
            return result.stdout.strip()
        else:  # Linux / X11
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2)
            return result.stdout.strip()
    except Exception:
        return ""


async def window_title_task(ws: websockets.WebSocketClientProtocol) -> None:
    """Poll the active window title every 3 s and push it to the server."""
    last_title: str = ""
    while True:
        await asyncio.sleep(3)
        title = get_active_window_title()
        if title != last_title:
            last_title = title
            try:
                await ws.send(json.dumps({"type": "window_title", "title": title}))
                log.debug("Window title: %r", title)
            except Exception:
                return   # ws closed – let the outer loop handle reconnect


def dispatch(raw: str | bytes) -> None:
    """Route incoming message to the appropriate handler."""
    # Binary frame → CH9329 protocol
    if isinstance(raw, (bytes, bytearray)):
        dispatch_ch9329(bytes(raw))
        return

    # Text frame → JSON protocol (browser web-terminal)
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Non-JSON text message ignored: %r", raw)
        return

    t = msg.get("type")
    if t == "key":
        handle_key(msg.get("data", ""))
    elif t == "hotkey":
        handle_hotkey(msg.get("combo", ""))
    elif t == "mouse_move":
        handle_mouse_move(int(msg["x"]), int(msg["y"]))
    elif t == "mouse_click":
        handle_mouse_click(int(msg["x"]), int(msg["y"]), msg.get("button", "left"))
    elif t == "mouse_scroll":
        handle_mouse_scroll(int(msg["x"]), int(msg["y"]),
                            int(msg.get("dx", 0)), int(msg.get("dy", 0)))
    else:
        log.debug("Unknown message type %r, ignored.", t)


# ---------------------------------------------------------------------------
# Main loop  (auto-reconnect)
# ---------------------------------------------------------------------------
async def run(server_url: str) -> None:
    agent_url = server_url.rstrip("/") + "/agent"
    log.info("Connecting to %s …", agent_url)

    while True:
        try:
            async with websockets.connect(agent_url) as ws:
                log.info("Agent connected. Waiting for commands…")

                async def _receive() -> None:
                    async for message in ws:
                        msg_id = None
                        if isinstance(message, str):
                            try:
                                parsed = json.loads(message)
                                msg_id = parsed.get("id")
                                if parsed.get("type") == "screenshot_request":
                                    await capture_and_send_screenshot(ws)
                                    if msg_id:
                                        try:
                                            await ws.send(json.dumps({"type": "ack", "id": msg_id, "ok": True}))
                                        except Exception:
                                            pass
                                    continue
                            except Exception:
                                pass
                        dispatch(message)
                        if msg_id:
                            try:
                                await ws.send(json.dumps({"type": "ack", "id": msg_id, "ok": True}))
                            except Exception:
                                pass

                receive_task = asyncio.create_task(_receive())
                title_task   = asyncio.create_task(window_title_task(ws))
                done, pending = await asyncio.wait(
                    {receive_task, title_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
        except (websockets.ConnectionClosed, OSError) as exc:
            log.warning("Disconnected (%s). Reconnecting in 5 s…", exc)
            await asyncio.sleep(5)
        except KeyboardInterrupt:
            log.info("Agent stopped by user.")
            break


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))

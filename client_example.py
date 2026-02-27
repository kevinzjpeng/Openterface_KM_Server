#!/usr/bin/env python3
"""
KeyMod – terminal keyboard client.

Every key you press is sent immediately to the server's /ws endpoint,
which relays it to the target PC agent in real time.  No Enter needed.

Usage
-----
  pip install websockets

  python client_example.py ws://localhost:8000/ws
  python client_example.py wss://xxxx.trycloudflare.com/ws

Press  Ctrl+C  or  Ctrl+Q  to quit.
"""

import asyncio
import json
import os
import sys
import termios
import tty
from contextlib import contextmanager

import websockets

# ---------------------------------------------------------------------------
# Raw terminal helpers
# ---------------------------------------------------------------------------

@contextmanager
def raw_terminal():
    """Put stdin in raw/cbreak mode so every keypress is available instantly."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key() -> str:
    """
    Read one logical keystroke from stdin.
    Returns a string: printable char, control char, or an ANSI escape sequence.
    Blocking, must be called from a thread.
    """
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # peek for up to 5 more bytes of an escape sequence (non-blocking)
        import select
        seq = ch
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.02)
            if not r:
                break
            c = sys.stdin.read(1)
            seq += c
            # CSI sequence ends on a letter (@ through ~)
            if c.isalpha() or c in "~ABCDFHPQRS":
                break
        return seq
    return ch


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(url: str) -> None:
    print(f"Connecting to {url} …", flush=True)

    try:
        async with websockets.connect(url) as ws:
            print(
                "Connected!  Every keystroke is sent immediately.\r\n"
                "Press Ctrl+C or Ctrl+Q to quit.\r\n",
                flush=True,
            )

            loop = asyncio.get_running_loop()
            stop = asyncio.Event()

            # ---- receive task: print server messages ---------------
            async def receive():
                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        t = msg.get("type")
                        if t == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                        elif t == "agent_status":
                            count = msg.get("count", 0)
                            status = f"\033[32mAgent ×{count} connected\033[0m" if count else "\033[33mNo agent\033[0m"
                            print(f"\r[server] {status}\r\n", end="", flush=True)
                        elif t == "echo":
                            # server echoes our keystrokes – display them
                            data = msg.get("data", "")
                            if data == "\r":
                                print("\r\n", end="", flush=True)
                            elif data == "\x7f":
                                print("\b \b", end="", flush=True)
                            elif data >= " " or data == "\t":
                                print(data, end="", flush=True)
                except websockets.ConnectionClosed:
                    pass
                finally:
                    stop.set()

            # ---- key reader: runs in a thread ----------------------
            def read_keys():
                with raw_terminal():
                    while not stop.is_set():
                        try:
                            key = read_key()
                        except Exception:
                            break

                        # Ctrl+C or Ctrl+Q → quit
                        if key in ("\x03", "\x11"):
                            stop.set()
                            break

                        payload = json.dumps({"type": "key", "data": key})
                        asyncio.run_coroutine_threadsafe(ws.send(payload), loop)

            receive_task = loop.create_task(receive())
            key_thread = loop.run_in_executor(None, read_keys)

            await stop.wait()
            receive_task.cancel()
            await ws.close()

    except (websockets.WebSocketException, OSError) as exc:
        # restore terminal before printing
        print(f"\r\n[error] {exc}\r\n", flush=True)
        sys.exit(1)

    print("\r\nDisconnected.\r\n", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    try:
        asyncio.run(run(sys.argv[1]))
    except KeyboardInterrupt:
        print("\r\nInterrupted.\r\n")

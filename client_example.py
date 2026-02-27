#!/usr/bin/env python3
"""
Minimal WebSocket client example.

Usage
-----
  # Install dependency once:
  pip install websockets

  # Connect to the ephemeral server (replace URL from job logs):
  python client_example.py wss://xxxx.trycloudflare.com/ws

  # Or, for a local server:
  python client_example.py ws://localhost:8765/ws

Once connected you can type messages and press Enter to send them.
Every message is broadcast to all connected clients, so open a second
terminal with the same command to see the broadcast in action.
Type  /quit  or press Ctrl-C to exit.
"""

import asyncio
import sys
import threading

import websockets


async def receive_loop(ws: websockets.WebSocketClientProtocol) -> None:
    """Print incoming messages from the server."""
    try:
        async for message in ws:
            print(f"\n[server] {message}")
            print("> ", end="", flush=True)
    except websockets.ConnectionClosed:
        print("\n[connection closed by server]")


async def send_loop(ws: websockets.WebSocketClientProtocol) -> None:
    """Read stdin lines and send them to the server."""
    loop = asyncio.get_event_loop()
    while True:
        # read_line runs in a thread so it doesn't block the event loop
        line: str = await loop.run_in_executor(None, lambda: input("> "))
        line = line.strip()
        if line.lower() == "/quit":
            await ws.close()
            break
        if line:
            await ws.send(line)


async def main(url: str) -> None:
    print(f"Connecting to {url} …")
    try:
        async with websockets.connect(url) as ws:
            print("Connected!  Type a message and press Enter.  /quit to exit.\n")
            await asyncio.gather(
                receive_loop(ws),
                send_loop(ws),
                return_exceptions=True,
            )
    except (websockets.WebSocketException, OSError) as exc:
        print(f"[error] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))

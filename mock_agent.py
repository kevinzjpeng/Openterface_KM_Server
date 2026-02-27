#!/usr/bin/env python3
"""
Mock agent – connects to /agent and prints every received message.
No keyboard/mouse control; useful for testing the server pipeline.
"""

import asyncio
import json
import sys
import struct

SERVER_URL = "ws://localhost:8000/agent"


def describe_message(raw):
    """Return a human-readable description of a received message."""
    if isinstance(raw, bytes):
        # Try to parse as CH9329 frame: 0x57 0xAB addr cmd len [payload] checksum
        if len(raw) >= 5 and raw[0] == 0x57 and raw[1] == 0xAB:
            addr = raw[2]
            cmd  = raw[3]
            dlen = raw[4]
            payload = raw[5:5 + dlen] if len(raw) >= 5 + dlen else raw[5:]
            cmd_names = {0x02: "KEYBOARD", 0x05: "MOUSE_REL", 0x06: "MOUSE_ABS"}
            cmd_str = cmd_names.get(cmd, f"CMD_0x{cmd:02X}")
            hex_payload = payload.hex(" ") if payload else "(empty)"
            return (
                f"[CH9329] {cmd_str}  addr=0x{addr:02X}  "
                f"len={dlen}  payload=[{hex_payload}]  "
                f"raw={raw.hex(' ')}"
            )
        # Generic binary
        return f"[BINARY {len(raw)} bytes] {raw.hex(' ')}"

    # Text – try JSON
    try:
        obj = json.loads(raw)
        kind = obj.get("type", "?")
        if kind == "ping":
            return "[PING] server keepalive"
        if kind == "agent_status":
            return f"[AGENT_STATUS] count={obj.get('count')}"
        return f"[JSON] {json.dumps(obj)}"
    except json.JSONDecodeError:
        return f"[TEXT] {raw}"


async def run(url: str):
    # Import websockets lazily so a missing package gives a clear error
    try:
        import websockets
    except ImportError:
        print("ERROR: 'websockets' package not found.  Run: pip install websockets")
        sys.exit(1)

    print(f"Connecting to {url} …")
    try:
        async with websockets.connect(url) as ws:
            print("Connected as agent.  Waiting for messages (Ctrl-C to quit).\n")
            async for message in ws:
                desc = describe_message(message)
                print(desc)
                # Reply to pings so the server doesn't time us out
                if isinstance(message, str):
                    try:
                        obj = json.loads(message)
                        if obj.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                    except json.JSONDecodeError:
                        pass
    except (OSError, websockets.exceptions.ConnectionRefusedError) as exc:
        print(f"Could not connect: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nDisconnected.")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else SERVER_URL
    asyncio.run(run(url))

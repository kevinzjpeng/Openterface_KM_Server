#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Openterface KM Server — run agent on target PC
#
# This script downloads and runs agent.py to connect a target PC to the tunnel.
# Usage (after tunnel is ready):
#
#   curl -sSL https://tunnel-url/run.sh | bash -s -- https://tunnel-url
#
# The script will automatically:
#   - Download agent.py from the tunnel
#   - Install required dependencies (websockets, pynput, mss, Pillow)
#   - Run it with the correct WebSocket URL (wss://)
#   - Pass through any additional arguments to agent.py
#
# Example with duration:
#   curl -sSL https://tunnel-url/run.sh | bash -s -- https://tunnel-url --duration 30
# ---------------------------------------------------------------------------
set -euo pipefail

# Tunnel URL: first arg (required), or env var, or localhost default
TUNNEL_URL="${1:-${TUNNEL_URL:-http://localhost:8000}}"

# Convert HTTPS to WSS for agent connection
WSS_URL="${TUNNEL_URL/https:/wss:}"
WSS_URL="${WSS_URL/http:/ws:}"

SCRIPT_URL="${TUNNEL_URL%/}/agent.py"

# ── Dependency checks ───────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 is required but was not found in PATH." >&2
  exit 1
fi

DOWNLOADER=""
if command -v curl &>/dev/null; then
  DOWNLOADER="curl"
elif command -v wget &>/dev/null; then
  DOWNLOADER="wget"
else
  echo "ERROR: curl or wget is required to download the script." >&2
  exit 1
fi

# ── Install required Python packages ────────────────────────────────────────
echo "Installing required Python packages …"
if ! python3 -m pip install -q websockets pynput mss Pillow 2>/dev/null; then
  # Try with --user flag if standard install fails (no admin rights)
  python3 -m pip install --user -q websockets pynput mss Pillow 2>/dev/null || {
    echo "Warning: Could not install all packages with pip. Attempting with sudo …"
    sudo python3 -m pip install -q websockets pynput mss Pillow || {
      echo "ERROR: Failed to install required packages." >&2
      exit 1
    }
  }
fi

# ── Download agent.py to a temp file ────────────────────────────────────────
TMP="$(mktemp /tmp/agent_XXXXXX.py)"
trap 'rm -f "$TMP"' EXIT

echo "Downloading agent.py from $SCRIPT_URL …"
if [ "$DOWNLOADER" = "curl" ]; then
  curl -sSL "$SCRIPT_URL" -o "$TMP"
else
  wget -qO "$TMP" "$SCRIPT_URL"
fi

# ── Run agent with WSS URL and any additional args ──────────────────────────
shift || true  # remove the tunnel URL from args
python3 "$TMP" "$WSS_URL" "$@"



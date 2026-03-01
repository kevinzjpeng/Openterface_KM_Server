#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Openterface KM Server — one-liner launcher
#
# Fetch and run trigger_build.py via Cloudflare tunnel (works with private repos):
#
#   TUNNEL_URL=https://tunnel-url.trycloudflare.com curl -sSL $TUNNEL_URL/run.sh | bash
#
# Pass extra args after a '--':
#   TUNNEL_URL=... curl -sSL ... | bash -s -- --duration 30
#
# Or use localhost for development:
#   curl -sSL http://localhost:8000/run.sh | bash
#
# Override credentials via env vars:
#   GITHUB_TOKEN=ghp_xxx GITHUB_REPO=owner/repo curl -sSL ... | bash
# ---------------------------------------------------------------------------
set -euo pipefail

# Tunnel URL can be passed as env var, first arg, or defaults to localhost
TUNNEL_URL="${TUNNEL_URL:-${1:-http://localhost:8000}}"
# Shift off the first arg if it was the tunnel URL
if [ $# -gt 0 ] && [[ "$1" == http* ]]; then
  shift
fi

SCRIPT_URL="${TUNNEL_URL%/}/trigger_build.py"

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

# ── Download trigger_build.py to a temp file ────────────────────────────────
TMP="$(mktemp /tmp/trigger_build_XXXXXX.py)"
trap 'rm -f "$TMP"' EXIT

echo "Downloading trigger_build.py …"
if [ "$DOWNLOADER" = "curl" ]; then
  curl -sSL "$SCRIPT_URL" -o "$TMP"
else
  wget -qO "$TMP" "$SCRIPT_URL"
fi

# ── Run it, forwarding all arguments ────────────────────────────────────────
python3 "$TMP" "$@"

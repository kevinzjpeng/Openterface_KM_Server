#!/usr/bin/env python3
"""
Trigger a GitHub Actions workflow_dispatch event from the command line.

Reads credentials from .env (or environment variables).
Optionally override repo, workflow, ref, and pass workflow inputs via CLI args.

One-liner (no local clone needed, works with private repos)
----------------------------------
  # After the tunnel is running, download run.sh directly from the tunnel URL:
  curl -sSL https://{TUNNEL_URL}/run.sh | bash

  # Or with credentials from environment variables:
  GITHUB_TOKEN=ghp_xxx GITHUB_REPO=owner/repo \\
    curl -sSL https://{TUNNEL_URL}/run.sh | bash

  # Pass extra arguments after '--':
  curl -sSL https://{TUNNEL_URL}/run.sh \\
    | bash -s -- --duration 30

Local usage
-----------
  python3 trigger_build.py                  # trigger + watch for tunnel URL
  python3 trigger_build.py --duration 20    # keep server alive 20 min
  python3 trigger_build.py --no-watch       # trigger and exit immediately
  python3 trigger_build.py --watch-only     # watch latest run (no trigger)
  python3 trigger_build.py --input debug=true --input platform=linux
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


# ---------------------------------------------------------------------------
# Load .env manually (no extra dependencies needed)
# ---------------------------------------------------------------------------
def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()

_TUNNEL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------
def _gh_get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def _find_run(repo: str, token: str, workflow: str, after_iso: str):
    """Return (run_id, html_url) for the first run created at/after after_iso."""
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows"
        f"/{workflow}/runs?per_page=5&event=workflow_dispatch"
    )
    for attempt in range(20):
        try:
            data = _gh_get(url, token)
            for run in data.get("workflow_runs", []):
                if run.get("created_at", "") >= after_iso:
                    return run["id"], run["html_url"]
        except Exception:
            pass
        print(f"  Waiting for run to appear … ({attempt + 1}/20)")
        time.sleep(3)
    return None


def _get_latest_run(repo: str, token: str, workflow: str):
    """Return (run_id, html_url) for the most recent run regardless of time."""
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows"
        f"/{workflow}/runs?per_page=1"
    )
    data = _gh_get(url, token)
    runs = data.get("workflow_runs", [])
    if not runs:
        return None
    return runs[0]["id"], runs[0]["html_url"]


def watch_for_tunnel_url(repo: str, token: str, run_id: int, dispatched_at: str = ""):
    """
    Poll the repo file `.tunnel-url` (written by the workflow using the
    contents API + GITHUB_TOKEN with contents:write permission).
    Returns the public HTTPS URL, or None on timeout / failure.
    """
    jobs_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    file_url = f"https://api.github.com/repos/{repo}/contents/.tunnel-url"

    print(f"\nWatching: https://github.com/{repo}/actions/runs/{run_id}")
    print("Polling .tunnel-url file in repo (ready in ~60 s) …\n")

    last_step = ""

    for attempt in range(70):   # poll up to ~7 minutes
        time.sleep(6)

        # -- Progress: show current step via Jobs API --
        try:
            data = _gh_get(jobs_url, token)
            jobs = data.get("jobs", [])
            if jobs:
                job        = jobs[0]
                status     = job["status"]
                conclusion = job.get("conclusion")
                steps      = job.get("steps", [])
                current    = next(
                    (s["name"] for s in steps if s["status"] == "in_progress"), None
                )
                label = current or status
                if label != last_step:
                    print(f"  [{status}] {label}")
                    last_step = label
                if status == "completed" and conclusion in ("failure", "cancelled", "timed_out"):
                    print(f"\nRun ended with: {conclusion}")
                    return None
        except Exception:
            pass

        # -- Poll .tunnel-url file --
        try:
            file_data  = _gh_get(file_url, token)
            import base64 as _b64
            raw  = _b64.b64decode(file_data["content"]).decode().strip()
            m    = _TUNNEL_RE.search(raw)
            if m:
                # Guard against a stale file from a previous run by checking
                # that the commit timestamp is close to dispatched_at.
                # Allow 90 s of clock skew between local machine and GitHub.
                commit_date = ""
                try:
                    commits_url = f"https://api.github.com/repos/{repo}/commits?path=.tunnel-url&per_page=1"
                    commits     = _gh_get(commits_url, token)
                    if commits:
                        commit_date = commits[0].get("commit", {}).get("committer", {}).get("date", "")[:19]
                except Exception:
                    pass

                # Build a threshold 90 s before dispatch to absorb clock skew
                try:
                    _dt = datetime.datetime.strptime(dispatched_at, "%Y-%m-%dT%H:%M:%S")
                    stale_threshold = (_dt - datetime.timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%S")
                except Exception:
                    stale_threshold = dispatched_at

                if dispatched_at and commit_date and commit_date < stale_threshold:
                    print(f"  [skip] Stale URL in file (committed {commit_date}, dispatched {dispatched_at})")
                    continue   # stale from a previous run
                return m.group(0)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:  # 404 = file not written yet
                print(f"  [file] HTTP {exc.code}")
        except Exception as exc:
            print(f"  [file] {exc}")

    print("Timed out waiting for tunnel URL (7 min).")
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remotely trigger a GitHub Actions workflow dispatch."
    )
    parser.add_argument(
        "--repo",
        default=os.getenv("GITHUB_REPO", ""),
        metavar="OWNER/REPO",
        help="Repository to target (default: $GITHUB_REPO)",
    )
    parser.add_argument(
        "--workflow",
        default=os.getenv("GITHUB_WORKFLOW", "build.yml"),
        metavar="FILE_OR_ID",
        help="Workflow file name or numeric ID (default: $GITHUB_WORKFLOW)",
    )
    parser.add_argument(
        "--ref",
        default=os.getenv("GITHUB_REF", "main"),
        metavar="BRANCH_OR_TAG",
        help="Git ref to run the workflow on (default: $GITHUB_REF)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        metavar="MINUTES",
        help="How long to keep the server alive in minutes (1-60, default: workflow default of 10)",
    )
    parser.add_argument(
        "--input",
        action="append",
        metavar="KEY=VALUE",
        dest="inputs",
        default=[],
        help="Workflow input (may be repeated, e.g. --input debug=true)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN", ""),
        metavar="TOKEN",
        help="GitHub PAT (default: $GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        default=True,
        help="After triggering, poll the run logs and print the tunnel URL (default: on)",
    )
    parser.add_argument(
        "--no-watch",
        action="store_false",
        dest="watch",
        help="Dispatch and exit without watching for the tunnel URL",
    )
    parser.add_argument(
        "--watch-only",
        action="store_true",
        help="Skip triggering; watch the most recent run instead",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()

    # Validate required values
    errors: list[str] = []
    if not args.token:
        errors.append("GITHUB_TOKEN is not set (use --token or set it in .env)")
    if not args.repo:
        errors.append("GITHUB_REPO is not set (use --repo or set it in .env)")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # --watch-only: skip dispatch, just watch the latest run
    if args.watch_only:
        print(f"Watch-only mode — finding latest run for {args.workflow} …")
        result = _get_latest_run(args.repo, args.token, args.workflow)
        if not result:
            print("ERROR: No runs found.", file=sys.stderr)
            sys.exit(1)
        run_id, html_url = result
        print(f"Latest run  : {html_url}")
        tunnel = watch_for_tunnel_url(args.repo, args.token, run_id, dispatched_at="")
        if tunnel:
            print(f"\n{'='*56}")
            print(f"  HTTP URL : {tunnel}")
            print(f"  WSS  URL : {tunnel.replace('https:', 'wss:')}/ws")
            print(f"  Agent    : python3 agent.py {tunnel.replace('https:', 'wss:')}")
            print(f"{'='*56}")
        sys.exit(0 if tunnel else 1)

    # Validate --duration
    if args.duration is not None:
        if not (1 <= args.duration <= 60):
            print("ERROR: --duration must be between 1 and 60 minutes", file=sys.stderr)
            sys.exit(1)

    # Parse --input KEY=VALUE pairs
    inputs: dict[str, str] = {}
    for kv in args.inputs:
        if "=" not in kv:
            print(f"ERROR: --input must be KEY=VALUE, got: {kv!r}", file=sys.stderr)
            sys.exit(1)
        k, _, v = kv.partition("=")
        inputs[k.strip()] = v.strip()

    # Inject duration_minutes if --duration was given
    if args.duration is not None:
        inputs["duration_minutes"] = str(args.duration)

    # Build request
    url = (
        f"https://api.github.com/repos/{args.repo}"
        f"/actions/workflows/{args.workflow}/dispatches"
    )
    payload: dict = {"ref": args.ref}
    if inputs:
        payload["inputs"] = inputs

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {args.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    print(f"Triggering  : {args.workflow}")
    print(f"Repository  : {args.repo}")
    print(f"Ref         : {args.ref}")
    if args.duration is not None:
        print(f"Duration    : {args.duration} minute(s)")
    if inputs:
        print(f"Inputs      : {inputs}")

    dispatched_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    try:
        with urllib.request.urlopen(req) as resp:
            print(f"\nSuccess! (HTTP {resp.status}) Workflow dispatch accepted.")
            print(f"Check runs at: https://github.com/{args.repo}/actions")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        print(f"\nERROR: GitHub API returned HTTP {exc.code}", file=sys.stderr)
        try:
            detail = json.loads(body_text)
            print(json.dumps(detail, indent=2), file=sys.stderr)
        except json.JSONDecodeError:
            print(body_text, file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"\nERROR: Network error – {exc.reason}", file=sys.stderr)
        sys.exit(1)

    if not args.watch:
        sys.exit(0)

    # Find the run we just triggered
    print("\nLocating the new run …")
    result = _find_run(args.repo, args.token, args.workflow, dispatched_at)
    if not result:
        print("Could not locate the run. Visit the Actions tab manually.", file=sys.stderr)
        sys.exit(1)

    run_id, html_url = result
    tunnel = watch_for_tunnel_url(args.repo, args.token, run_id, dispatched_at)
    if tunnel:
        print(f"\n{'='*56}")
        print(f"  HTTP URL : {tunnel}")
        print(f"  WSS  URL : {tunnel.replace('https:', 'wss:')}/ws")
        print(f"  Agent    : python3 agent.py {tunnel.replace('https:', 'wss:')}")
        print(f"{'='*56}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

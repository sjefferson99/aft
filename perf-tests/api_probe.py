"""Measure GET /api/boards/:id/cards server-side cost via the PERF_PROBE
log lines emitted by server/_perf_probe.py (enabled with PERF_PROBE=1 — see
perf-tests/README.md).

Reads recent container logs rather than parsing stdout live, so it works
whether or not run_all.py's own requests are the only recent traffic —
it matches on path and takes the most recent N matching lines.
"""
import re
import subprocess
import time

import requests

PROBE_LINE_RE = re.compile(
    r"PERF_PROBE (?P<method>\S+) (?P<path>\S+) status=(?P<status>\d+) "
    r"ms=(?P<ms>[\d.]+) queries=(?P<queries>\d+) bytes=(?P<bytes>\d+)"
)


def fetch_recent_probe_lines(path_substring, limit=200):
    out = subprocess.run(
        ["docker", "compose", "logs", "server", "--tail", "500"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    lines = []
    for line in out.stdout.splitlines():
        if "PERF_PROBE" not in line or path_substring not in line:
            continue
        m = PROBE_LINE_RE.search(line)
        if m:
            lines.append(m.groupdict())
    return lines[-limit:]


def measure_board_endpoint(base_url, session, board_id, repeat=5):
    """Hit the board endpoint `repeat` times, then read back the matching
    PERF_PROBE log lines for query count / server ms / bytes.

    Returns dict with per-run client-observed wall time and, if the probe
    is enabled, server-side query counts and server-measured ms.
    """
    path = f"/api/boards/{board_id}/cards"
    client_times_ms = []

    for _ in range(repeat):
        start = time.perf_counter()
        resp = session.get(f"{base_url}{path}", params={"archived": "false"}, timeout=30)
        elapsed_ms = (time.perf_counter() - start) * 1000
        resp.raise_for_status()
        client_times_ms.append(elapsed_ms)

    probe_lines = fetch_recent_probe_lines(path, limit=repeat)

    result = {
        "endpoint": path,
        "repeat": repeat,
        "client_observed_ms": client_times_ms,
        "response_bytes": len(resp.content),
        "probe_enabled": len(probe_lines) > 0,
    }

    if probe_lines:
        result["server_ms"] = [float(l["ms"]) for l in probe_lines]
        result["query_counts"] = [int(l["queries"]) for l in probe_lines]

    return result

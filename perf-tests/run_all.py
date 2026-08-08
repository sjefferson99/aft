"""Orchestrate a full performance measurement run: host specs, API
query-count/timing/payload-size, and a browser-driven board-load trace.
Writes a timestamped JSON result to perf-tests/results/ and appends a
summary row to perf-tests/results/history.md.

Usage:
    python perf-tests/run_all.py --board-id 1 --label baseline-tier0
    python perf-tests/run_all.py --board-id 1 --label after-tier1 --repeat 3

Prerequisites: stack running (docker compose up -d --build), board already
seeded (perf-tests/seed_board.py), and PERF_PROBE=1 set on the server
(compose.override.yml — see perf-tests/README.md) for query-count numbers.
Without the probe enabled, API measurement still records client-observed
timing and payload size, just not server-side query counts.
"""
import argparse
import datetime
import json
import statistics
from pathlib import Path

from api_probe import measure_board_endpoint
from browser_probe import measure_board_load
from host_specs import collect as collect_host_specs
from seed_board import ensure_admin_and_login, BASE_URL

RESULTS_DIR = Path(__file__).parent / "results"


def _stats(values):
    if not values:
        return None
    return {
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
        "n": len(values),
    }


def run(board_id, label, api_repeat, browser_repeat, headless):
    print("Collecting host specs...")
    host = collect_host_specs()

    print("Logging in for API measurement...")
    session = ensure_admin_and_login()

    print(f"Measuring API endpoint ({api_repeat} requests)...")
    api_result = measure_board_endpoint(BASE_URL, session, board_id, repeat=api_repeat)

    print(f"Measuring browser board load ({browser_repeat} run(s))...")
    browser_runs = []
    for i in range(browser_repeat):
        print(f"  run {i + 1}/{browser_repeat}...")
        browser_runs.append(measure_board_load(board_id, headless=headless))

    summary = {
        "label": label,
        "board_id": board_id,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": host,
        "api": {
            "endpoint": api_result["endpoint"],
            "response_bytes": api_result["response_bytes"],
            "probe_enabled": api_result["probe_enabled"],
            "client_observed_ms": _stats(api_result["client_observed_ms"]),
        },
        "browser": {
            "runs": browser_runs,
            "layout_count": _stats([r["layout_count"] for r in browser_runs]),
            "recalc_style_count": _stats([r["recalc_style_count"] for r in browser_runs]),
            "script_time_ms": _stats([r["script_time_ms"] for r in browser_runs]),
            "long_task_count": _stats([r["long_task_count"] for r in browser_runs]),
            "long_task_total_ms": _stats([r["long_task_total_ms"] for r in browser_runs]),
        },
    }

    if api_result["probe_enabled"]:
        summary["api"]["server_ms"] = _stats(api_result["server_ms"])
        summary["api"]["query_counts"] = _stats(api_result["query_counts"])
    else:
        print(
            "WARNING: PERF_PROBE not detected in recent server logs — "
            "server-side query counts not captured. See perf-tests/README.md "
            "to enable it via compose.override.yml."
        )

    RESULTS_DIR.mkdir(exist_ok=True)
    ts_slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{ts_slug}_{label}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")

    _append_history_row(summary)

    return summary


def _append_history_row(summary):
    history_path = RESULTS_DIR / "history.md"
    header = (
        "| Timestamp | Label | Board | Payload (bytes) | Client ms (median) | "
        "Server ms (median) | SQL queries (median) | Layout count (median) | "
        "Long tasks (median) | Long task ms (median) |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    if not history_path.exists():
        history_path.write_text(header, encoding="utf-8")

    api = summary["api"]
    browser = summary["browser"]
    row = "| {ts} | {label} | {board} | {bytes} | {client} | {server} | {queries} | {layout} | {lt_count} | {lt_ms} |\n".format(
        ts=summary["timestamp"],
        label=summary["label"],
        board=summary["board_id"],
        bytes=api["response_bytes"],
        client=api["client_observed_ms"]["median"] if api["client_observed_ms"] else "-",
        server=api.get("server_ms", {}).get("median", "-") if api.get("server_ms") else "n/a",
        queries=api.get("query_counts", {}).get("median", "-") if api.get("query_counts") else "n/a",
        layout=browser["layout_count"]["median"] if browser["layout_count"] else "-",
        lt_count=browser["long_task_count"]["median"] if browser["long_task_count"] else "-",
        lt_ms=browser["long_task_total_ms"]["median"] if browser["long_task_total_ms"] else "-",
    )
    with history_path.open("a", encoding="utf-8") as f:
        f.write(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", type=int, required=True)
    parser.add_argument("--label", required=True, help="Tag for this run, e.g. baseline-tier0, after-tier1")
    parser.add_argument("--api-repeat", type=int, default=5)
    parser.add_argument("--browser-repeat", type=int, default=3)
    parser.add_argument("--headed", action="store_true", help="Show the browser window (default: headless)")
    args = parser.parse_args()

    summary = run(
        board_id=args.board_id,
        label=args.label,
        api_repeat=args.api_repeat,
        browser_repeat=args.browser_repeat,
        headless=not args.headed,
    )

    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

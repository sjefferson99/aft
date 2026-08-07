"""Drive a headless Chromium session against a live board and capture a
Chrome DevTools Protocol trace of a full board load, then summarize
scripting time, layout (reflow) count, and long tasks.

Card-drag timing is intentionally NOT automated here — board.js uses native
HTML5 drag-and-drop (`draggable="true"` + dragstart/dragover/drop), and
Chrome only synthesizes that event sequence for a real OS-level drag
gesture. Neither plain page.mouse events nor Playwright's drag_to()/CDP
Input.setInterceptDrags plumbing could be made to reliably fire a realistic
number of dragover events per drag in headless testing (investigated and
documented in the PR that introduced this module) — a low dragover count
would understate the real cost and produce a misleading number.

For drag timing, follow the manual steps in perf-tests/README.md
("Measuring drag performance") using Chrome DevTools' own Performance
panel on a real drag gesture — the ground truth this module can't safely
approximate.

Uses a raw CDP Tracing session (Tracing.start/Tracing.end) rather than
Playwright's own `tracing` API, because we need Chrome's Performance-panel-
style trace events (layout counts, long tasks) rather than Playwright's
action log.
"""
import json
import time

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost"
TEST_ADMIN_EMAIL = "test-admin@localhost"
TEST_ADMIN_PASSWORD = "TestAdmin123!"

TRACE_CATEGORIES = [
    "devtools.timeline",
    "disabled-by-default-devtools.timeline",
    "v8.execute",
    "disabled-by-default-v8.compile",
    "blink.user_timing",
]


def _login_via_ui(page):
    page.goto(f"{BASE_URL}/login.html")
    page.fill("#email", TEST_ADMIN_EMAIL)
    page.fill("#password", TEST_ADMIN_PASSWORD)
    page.click("#loginButton")
    page.wait_for_url(lambda url: "login.html" not in url, timeout=15000)


def _summarize_trace(events):
    """Reduce raw CDP trace events to headline metrics.

    - layout_count: number of 'Layout' events (each is one forced/scheduled
      reflow).
    - recalc_style_count: number of 'RecalculateStyles'/'UpdateLayoutTree'
      events.
    - script_time_ms: total duration of 'EvaluateScript' + 'FunctionCall' +
      'RunMicrotasks' events (approximation of scripting cost).
    - long_task_count / long_task_total_ms: tasks with duration > 50ms,
      the standard "long task" threshold used by the Long Tasks API.
    """
    layout_count = 0
    recalc_style_count = 0
    script_time_us = 0
    long_tasks = []

    for ev in events:
        name = ev.get("name")
        dur = ev.get("dur", 0)  # microseconds, complete events only
        if name == "Layout":
            layout_count += 1
        elif name in ("RecalculateStyles", "UpdateLayoutTree"):
            recalc_style_count += 1
        elif name in ("EvaluateScript", "FunctionCall", "RunMicrotasks"):
            script_time_us += dur
        if ev.get("ph") == "X" and dur > 50_000:  # complete event, >50ms
            long_tasks.append(dur / 1000.0)

    return {
        "layout_count": layout_count,
        "recalc_style_count": recalc_style_count,
        "script_time_ms": round(script_time_us / 1000.0, 1),
        "long_task_count": len(long_tasks),
        "long_task_total_ms": round(sum(long_tasks), 1),
        "raw_event_count": len(events),
    }


def measure_board_load(board_id, headless=True):
    """Load the board page fresh and capture a CDP trace of the load,
    including the requestAnimationFrame overflow-measurement pass.
    Returns a dict of summarized trace metrics.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        _login_via_ui(page)

        cdp = context.new_cdp_session(page)
        trace_events = []

        def on_data_collected(params):
            trace_events.extend(params.get("value", []))

        cdp.on("Tracing.dataCollected", on_data_collected)
        tracing_complete = {"done": False}
        cdp.on("Tracing.tracingComplete", lambda _params: tracing_complete.update(done=True))

        cdp.send("Tracing.start", {
            "categories": ",".join(TRACE_CATEGORIES),
            "options": "sampling-frequency=1000",
        })

        page.goto(f"{BASE_URL}/board.html?id={board_id}", wait_until="networkidle")
        page.wait_for_selector(".card", timeout=20000)
        page.wait_for_timeout(500)  # let requestAnimationFrame overflow pass settle

        cdp.send("Tracing.end")
        deadline = time.time() + 10
        while not tracing_complete["done"] and time.time() < deadline:
            page.wait_for_timeout(100)

        result = _summarize_trace(trace_events)
        browser.close()
        return result


if __name__ == "__main__":
    import sys
    board_id = sys.argv[1] if len(sys.argv) > 1 else "1"
    print(json.dumps(measure_board_load(board_id), indent=2))

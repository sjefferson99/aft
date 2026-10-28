"""Time repeated BoardManager.renderBoard() calls on an already-loaded board.

browser_probe.py measures a cold board load, which bundles network, JSON
parse and the first render together, and its trace metrics are bimodal run
to run (see the item 2.1 notes in docs/PERFORMANCE_board_updates.md).
Every WebSocket card update re-runs renderBoard() on a warm page, so this
probe isolates that cost: it loads the board once, then calls renderBoard()
repeatedly and reports
  - sync_ms: the synchronous renderBoard() call (HTML build, innerHTML
    parse, listener wiring, scroll restore);
  - frame_ms: from the call until two animation frames later, which adds
    style/layout/paint and the overflow-measurement requestAnimationFrame.

Compare runs on the same host and board only. Usage:
    python perf-tests/render_probe.py <board_id> [renders]
"""
import json
import statistics

from playwright.sync_api import sync_playwright

from browser_probe import BASE_URL, _login_via_ui

WARMUP_RENDERS = 3

RENDER_LOOP_JS = """async ({ renders, warmup }) => {
  const boardManager = window.boardManager;
  const sync = [];
  const frame = [];
  for (let i = 0; i < renders + warmup; i++) {
    const start = performance.now();
    boardManager.renderBoard();
    const rendered = performance.now();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const painted = performance.now();
    if (i >= warmup) {
      sync.push(rendered - start);
      frame.push(painted - start);
    }
  }
  return { sync, frame, cards: document.querySelectorAll('.card').length };
}"""


def _stats(values):
    return {
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
        "n": len(values),
    }


def measure_rerender(board_id, renders=20, headless=True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1600, "height": 900})

        _login_via_ui(page)
        page.goto(f"{BASE_URL}/board.html?id={board_id}", wait_until="networkidle")
        page.wait_for_selector(".card", timeout=20000)
        page.wait_for_timeout(1000)  # let the initial render and its rAF pass settle

        raw = page.evaluate(RENDER_LOOP_JS, {"renders": renders, "warmup": WARMUP_RENDERS})
        browser.close()

    return {
        "card_count": raw["cards"],
        "sync_ms": _stats(raw["sync"]),
        "frame_ms": _stats(raw["frame"]),
    }


if __name__ == "__main__":
    import sys
    board_id = sys.argv[1] if len(sys.argv) > 1 else "1"
    renders = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(json.dumps(measure_rerender(board_id, renders), indent=2))

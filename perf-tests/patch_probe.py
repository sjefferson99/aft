"""Time how long a board takes to settle after another client edits a card.

Card events from other clients are patched into the board in place (issue
#525 item 2.3c) instead of reloading it. This probe edits a card's title via
the API, which the page receives as a `card_updated` broadcast, and reports
  - settle_ms: from the broadcast reaching the page until the new title is
    shown, no reload is pending or in flight, and two animation frames have
    passed;
  - load_calls / render_calls: loadBoard()/renderBoard() calls per edit.

It runs twice on the same page: `patch` (the normal path) and `reload`, with
patchCard() stubbed to return false so every event takes the fallback full
reload, as all card events did before 2.3c.

Compare runs on the same host and board only. Usage:
    python perf-tests/patch_probe.py <board_id> [edits]
"""
import json
import statistics
import uuid

from playwright.sync_api import sync_playwright

from browser_probe import BASE_URL, _login_via_ui
from seed_board import ensure_admin_and_login

WARMUP_EDITS = 2

INSTALL_SPY_JS = """() => {
  const boardManager = window.boardManager;
  window.__probeCalls = { load: 0, render: 0 };
  const loadBoard = boardManager.loadBoard.bind(boardManager);
  const renderBoard = boardManager.renderBoard.bind(boardManager);
  boardManager.loadBoard = (...args) => { window.__probeCalls.load += 1; return loadBoard(...args); };
  boardManager.renderBoard = (...args) => { window.__probeCalls.render += 1; return renderBoard(...args); };
}"""

# Starts waiting before the API call; the result is read back from
# window.__probeResult once the edit has been made.
ARM_JS = """({ cardId, title }) => {
  const boardManager = window.boardManager;
  const socket = boardManager.wsManager.socket;
  window.__probeCalls.load = 0;
  window.__probeCalls.render = 0;
  let received = null;
  const onAny = (event) => {
    if (event === 'card_updated' && received === null) received = performance.now();
  };
  socket.onAny(onAny);
  window.__probeResult = new Promise((resolve) => {
    const check = () => {
      const titleElement = document.querySelector(`.card[data-card-id="${cardId}"] .card-title`);
      const settled = received !== null
        && titleElement && titleElement.textContent === title
        && !boardManager.currentLoadController
        && !boardManager.boardReloadDebounceTimeoutId;
      if (!settled) {
        requestAnimationFrame(check);
        return;
      }
      requestAnimationFrame(() => requestAnimationFrame(() => {
        socket.offAny(onAny);
        resolve({ settle: performance.now() - received, ...window.__probeCalls });
      }));
    };
    check();
  });
}"""


def _stats(values):
    return {
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
        "n": len(values),
    }


def _run_edits(page, session, card_id, edits):
    settle, loads, renders = [], [], []
    for i in range(edits + WARMUP_EDITS):
        title = f"Probe edit {uuid.uuid4().hex[:8]}"
        page.evaluate(ARM_JS, {"cardId": card_id, "title": title})
        resp = session.patch(f"{BASE_URL}/api/cards/{card_id}", json={"title": title}, timeout=30)
        resp.raise_for_status()
        result = page.evaluate("() => window.__probeResult")
        if i >= WARMUP_EDITS:
            settle.append(result["settle"])
            loads.append(result["load"])
            renders.append(result["render"])
        page.wait_for_timeout(300)
    return {
        "settle_ms": _stats(settle),
        "load_calls": _stats(loads),
        "render_calls": _stats(renders),
    }


def measure_patch(board_id, edits=10, headless=True):
    session = ensure_admin_and_login()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1600, "height": 900})

        _login_via_ui(page)
        page.goto(f"{BASE_URL}/board.html?id={board_id}", wait_until="networkidle")
        page.wait_for_selector(".card", timeout=20000)
        page.wait_for_function(
            "() => window.boardManager.wsManager?.socket?.connected"
            " && !window.boardManager.assigneeFilterVisibilityWatcherId",
            timeout=20000,
        )
        page.wait_for_timeout(1000)  # let the initial render and its rAF pass settle
        page.evaluate(INSTALL_SPY_JS)

        card_id = page.evaluate("() => Number(document.querySelector('.card').dataset.cardId)")
        card_count = page.evaluate("() => document.querySelectorAll('.card').length")

        patch = _run_edits(page, session, card_id, edits)
        page.evaluate("() => { window.boardManager.patchCard = () => false; }")
        reload = _run_edits(page, session, card_id, edits)
        browser.close()

    return {"card_count": card_count, "patch": patch, "reload": reload}


if __name__ == "__main__":
    import sys
    board_id = sys.argv[1] if len(sys.argv) > 1 else "1"
    edits = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    print(json.dumps(measure_patch(board_id, edits), indent=2))

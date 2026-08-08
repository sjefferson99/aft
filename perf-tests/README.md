# AFT Performance Test Harness

A repeatable, host-spec-aware harness for measuring board performance at
scale. Originated from the Tier 1 board performance work in
[docs/PERFORMANCE_board_updates.md](../docs/PERFORMANCE_board_updates.md)
(issue #523) and kept as a standing module — re-run it whenever board
rendering/update paths change, or periodically to catch regressions that
unit/API tests won't.

This is a manual/on-demand tool, not part of CI. It requires a live Docker
stack and produces host-dependent absolute numbers — useful for **relative**
comparison (before/after a change, same machine) and for spotting regressions
over time on the same dev host, not for cross-machine benchmarking.

## What it measures

1. **Server-side cost** of `GET /api/boards/:id/cards`: SQL query count,
   wall-clock time, response size. Via `server/_perf_probe.py`.
2. **Payload size and gzip potential** for the board JSON and static JS/CSS,
   and whether nginx is currently serving compressed responses at all
   (`payload_check.py`).
3. **Client-side board-load cost**: Playwright-driven board load using a raw
   Chrome DevTools Protocol trace — scripting time, layout (reflow) count,
   long tasks (`browser_probe.py`).
4. **Card-drag cost**: manual procedure using Chrome DevTools' own
   Performance panel — see [DRAG_MEASUREMENT.md](DRAG_MEASUREMENT.md).
   Automating this with headless Chromium was attempted and abandoned; see
   that file and the docstring at the top of `browser_probe.py` for why.
5. **Host specs**, recorded alongside every run so numbers are attributable.

## Prerequisites

- Docker stack running: `docker compose up -d --build`
- Python venv with `requests` and `playwright` (already present in the
  repo's `.venv` — see `server/requirements-dev.txt` / `ui-tests/`)
- Chromium installed for Playwright: `python -m playwright install chromium`
  (already done if `ui-tests/` has been run before)

## Enabling the server-side probe

The query-count/timing probe (`server/_perf_probe.py`) is off by default —
zero cost in normal operation, not imported unless `PERF_PROBE=1`. Enable it
for a measurement session via `compose.override.yml` (gitignored, safe to
keep locally):

```yaml
services:
  server:
    environment:
      - PERF_PROBE=1
```

Then `docker compose up -d --build server`. `run_all.py` reads the resulting
log lines back automatically; or watch live with
`docker compose logs -f server | grep PERF_PROBE`.

**Remove `compose.override.yml` (or the `PERF_PROBE` line) after
measuring** — it's dev-only instrumentation and logs a line per request.

## Usage

### 1. Seed a large board

```sh
.venv/Scripts/python.exe perf-tests/seed_board.py --columns 8 --cards-per-column 100
```

Options: `--board-name`, `--columns`, `--cards-per-column`,
`--checklist-items-per-card`, `--comments-per-card`. Uses the same
test-admin bootstrap pattern as `ui-tests/conftest.py`
(`test-admin@localhost` / `TestAdmin123!`) and imports via the native AFT
JSON import endpoint (`POST /api/boards/import`), so it exercises a real
code path rather than writing to the DB directly. Prints the board id and
URL when done.

### 2. Run the full measurement suite

```sh
.venv/Scripts/python.exe perf-tests/run_all.py --board-id 1 --label baseline-tier0
```

This:
- Records host specs (CPU, RAM, Docker resources, OS, MySQL/Python versions)
- Hits the board endpoint N times (`--api-repeat`, default 5), capturing
  size/timing/query-count from the `PERF_PROBE` log lines (requires the
  probe enabled — see above; if not enabled, still records client-observed
  timing and payload size)
- Drives a headless Chromium session via Playwright N times
  (`--browser-repeat`, default 3): loads the board page, captures a CDP
  trace, and extracts scripting time / layout count / long-task count
- Writes a timestamped JSON result to `perf-tests/results/` and appends a
  row to `perf-tests/results/history.md`

`--label` tags the run (e.g. `baseline-tier0`, `after-tier1`) so results are
easy to diff later. Pass `--headed` to watch the browser phase run instead
of headless.

### 3. Check payload/compression separately

```sh
.venv/Scripts/python.exe perf-tests/payload_check.py --board-id 1
```

Reports uncompressed size, gzip -9 size/ratio, and whether nginx is
currently sending `Content-Encoding: gzip` for the board JSON endpoint plus
`board.js`/`board.css`. Useful in isolation when validating item 1.4
(enable gzip in nginx) without re-running the full suite.

### 4. Measure drag performance (manual)

Follow [DRAG_MEASUREMENT.md](DRAG_MEASUREMENT.md) — a ~3 minute manual
procedure using Chrome DevTools' Performance panel on a real drag gesture.

### 5. Compare runs

Each JSON file in `perf-tests/results/` is self-contained (host specs +
metrics). `history.md` is a running table — diff two rows to see the delta
from a change.

## Files

| File | Purpose |
|---|---|
| `seed_board.py` | Creates a large synthetic board via the API |
| `host_specs.py` | Collects CPU/RAM/OS/Docker/DB version info |
| `api_probe.py` | Repeats the board-endpoint GET and reads back `PERF_PROBE` log lines |
| `browser_probe.py` | Playwright + raw CDP trace of a board load |
| `payload_check.py` | Payload size / gzip ratio / actual `Content-Encoding` check |
| `run_all.py` | Orchestrates host specs + API + browser measurement; writes `results/` |
| `DRAG_MEASUREMENT.md` | Manual Chrome DevTools procedure for drag timing |
| `results/` | Timestamped JSON results + `history.md` summary table (tracked in git) |
| `results/traces/` | Saved DevTools trace files from manual drag measurement (gitignored — can be large) |
| `../server/_perf_probe.py` | Dev-only, env-gated SQLAlchemy query counter + request timer (not imported unless `PERF_PROBE=1`) |

## Notes on interpreting results

- Absolute times are only meaningful relative to other runs on **this same
  host**, in **this same state** (Docker resource limits, other running
  containers, thermal throttling, etc. all matter). `host_specs.py` records
  what it can, but it can't control for background load at run time.
- The synthetic seed data (lorem-ipsum text) compresses better under gzip
  than typical real-world card text will — the measured ~37× ratio on the
  board JSON is an upper bound, not a promise. Treat gzip ratios as
  directional.
- The browser-load trace numbers are a small sample (`--browser-repeat`,
  default 3), not a statistical distribution. `run_all.py` reports
  min/median/max across the repeats; re-run with a higher count if a result
  looks noisy.
- Drag timing is manual by design — see
  [DRAG_MEASUREMENT.md](DRAG_MEASUREMENT.md) for why headless automation
  was abandoned.

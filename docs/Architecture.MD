# AFT Architecture Decisions

This document captures high-level architecture decisions and the rationale behind them.

## Background Services: Daemon Threads vs. Celery

**Decision**: Use in-process daemon-thread schedulers instead of Celery.

**Rationale**:
- Current workload is periodic and predictable (backups, recurring card creation, housekeeping checks)
- No immediate need for distributed workers, queue routing, or advanced retry orchestration
- Simpler deployment and operations (no separate broker/worker stack)
- Lower maintenance overhead for a self-hosted deployment model

**When to reconsider**:
- High task volume or long-running jobs
- Need for isolated worker scaling
- Task prioritization, delayed retries, and queue-level observability requirements

**Implementation references**:
- `server/backup_scheduler.py`
- `server/card_scheduler.py`
- `server/housekeeping_scheduler.py`

## Board Rendering: Full Reload vs. Incremental Updates

**Decision (current state, not final)**: The board view fully reloads (re-fetches and
re-renders every card in every column) on essentially any change, including changes made by
other clients over WebSocket. This was fine at small scale and broke down badly once real
boards reached 100+ cards per column — see
[docs/PERFORMANCE_board_updates.md](../docs/PERFORMANCE_board_updates.md) for the full
investigation (issue #523).

**Why it happened**: the reload-everything approach is the simplest possible way to keep
every client's view consistent, and nothing in the original design constrained board size.
Server query patterns (N+1s on relationships), payload shape (full comment bodies in a list
endpoint), and client rendering (interleaved DOM read/write loops causing layout thrash) all
independently assumed boards would stay small.

**What changed (Tier 1, implemented)**: query batching, WebSocket `skip_sid` so the acting
client doesn't reload its own change, debounced reloads, gzip, a trimmed list-endpoint
payload, and — the single highest-value fix — splitting a DOM read/write loop that was
forcing a layout recalculation per card on every render. Measured effect on an 800-card
board: server time 902ms → 102ms, SQL queries 1,622 → 38, forced layout events 806 → ~17.
Full before/after numbers in the performance doc.

**What has not changed**: the board still does a full reload on every mutation — Tier 1
made that reload far cheaper, it did not remove it. Incremental DOM patching (only touching
the card/column that actually changed) is scoped as Tier 2 in the same document and has not
been built yet.

**When to reconsider the full-reload model**: if Tier 2's incremental-patching work (item
2.3) lands and the reload-per-change pattern is fully replaced, this section should be
updated to reflect the new model. Until then, any change to a board-scale endpoint or to
`www/js/board.js` rendering code should be checked against
[CONTRIBUTING.md § Performance Considerations](../CONTRIBUTING.md#performance-considerations)
and measured with [perf-tests/](../perf-tests/) on a large seeded board — the failure mode
here is invisible on a small dev board and only shows up at real-world scale.

**Implementation references**:
- `docs/PERFORMANCE_board_updates.md` — full investigation, tiered fix list, measurements
- `perf-tests/` — reusable measurement harness (seed a large board, measure server/client
  cost, compare before/after)
- `server/_perf_probe.py` — dev-only query-count/timing instrumentation, gated behind
  `PERF_PROBE=1`, zero cost otherwise

## Single Container Runtime vs. Microservices

**Decision**: Keep API and schedulers in the same server runtime.

**Rationale**:
- Simpler startup and orchestration
- Shared access to Flask app context, models, and utility modules
- Fewer moving parts for small-team/self-hosted operations

**Trade-offs**:
- Service lifecycle is coupled (scheduler restarts when server restarts)
- Independent horizontal scaling of background processors is limited

**Current safeguards**:
- Scheduler initialization lock to avoid duplicate startup in multi-process/container races
- Health monitoring integrated with housekeeping checks

**Implementation references**:
- `server/app.py` (`init_backup_scheduler()`, `init_card_scheduler()`, `init_housekeeping_scheduler()`)
- `server/scheduler_lock.py`

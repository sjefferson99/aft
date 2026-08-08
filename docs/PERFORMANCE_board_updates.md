# Performance Review: Board Updates at Scale

Status: Tier 1 implemented and measured (this branch); Tier 2/3 still proposal-only
Scope: the board view (`www/js/board.js`, `www/css/board.css`) and the board read/write API (`server/card_routes.py`, `server/board_routes.py`, `server/broadcasting.py`)
Trigger: board interactions degrade sharply once columns exceed ~100 cards, including when the change is on a *different* column

## Method and honesty note

This review started from reading the code paths end to end, not a profiler trace. Every
finding below cites the specific file and line it comes from, and the reasoning for why it
costs time is stated so it can be checked. A baseline has since been captured (see
[Baseline measurements](#baseline-measurements) below) using the harness in
[perf-tests/](../perf-tests/) — the code-reading predictions and the measured numbers agree
closely, which is the main thing this section is for. The *ordering* of impact on the not-yet
measured Tier 2/3 items is still a prediction; re-run the harness after each tier lands.

Working assumption for the arithmetic: a board with 8 columns × 100 cards = 800 cards. The
measured baseline below uses exactly this shape, seeded via
[perf-tests/seed_board.py](../perf-tests/seed_board.py).

---

## Baseline measurements

Captured 2026-08-07 on the primary dev host (AMD Ryzen 7 7800X3D, 16 logical processors,
31 GB RAM, Docker Desktop with 16 CPUs / 15.2 GB allocated, MySQL 9.5.0, all containers
local — no network hop). Full host specs and raw data in
[perf-tests/results/](../perf-tests/results/); this is a single dev machine, so treat
absolute numbers as relative-comparison baselines for *this host*, not portable benchmarks.
Reproduce with `perf-tests/run_all.py` — see [perf-tests/README.md](../perf-tests/README.md).

Board: 8 columns × 100 cards = 800 cards, 3 checklist items/card, 2 comments/card.

| Metric | Measured | Source |
|---|---|---|
| `GET /api/boards/:id/cards` — server time | 902.5ms (median of 5) | `server/_perf_probe.py` via `perf-tests/api_probe.py` |
| SQL queries per request | **1,622** (constant across all 5 runs) | same |
| Response payload size | 1,800,087 bytes (1.8 MB) | same |
| Client-observed round trip | 910.1ms (median of 5) | same |
| Board JSON gzip -9 size | 49,065 bytes → **36.7× smaller** | `perf-tests/payload_check.py` |
| Currently served with `Content-Encoding: gzip`? | **No** — nginx has no gzip config | same |
| `board.js` size / gzip -9 | 358,248 bytes → 66,146 bytes (**5.4×**) | same |
| `board.css` size / gzip -9 | 50,803 bytes → 8,185 bytes (**6.2×**) | same |
| Browser: forced `Layout` events during one board load | 806 (median of 3) | `perf-tests/browser_probe.py`, CDP trace |
| Browser: `RecalculateStyles`/`UpdateLayoutTree` events | ~810 (median of 3) | same |
| Browser: long tasks (>50ms) during load | 6 (median), totalling ~1.3s | same |

This confirms, with numbers rather than arithmetic: the query count is exactly what the
code-reading predicted (1,622 ≈ 2 queries × 800 cards + a handful of board/column/user
queries — see item 1.1), the payload is large enough that gzip is a 36.7× win on this
dataset (item 1.4/1.5), and a single board load forces roughly one `Layout` recalculation
per card (item 1.6/2.1) — 806 forced layouts is not "some layout thrash," it is one per card
in the board, on every load.

### Drag measurement (manual, Chrome DevTools)

Card-drag timing could not be reliably automated — Chrome only synthesizes native HTML5
drag events (`dragover`/`drop`, which `setupDragAndDrop()` at
[board.js:4267](../www/js/board.js#L4267) listens for) for a real OS-level drag gesture, and
neither Playwright's `drag_to()` helper nor manually driving `Input.dispatchDragEvent` via
CDP could be made to fire a realistic number of `dragover` events per drag headlessly (full
investigation notes in `perf-tests/browser_probe.py`). Measured manually instead, following
[perf-tests/DRAG_MEASUREMENT.md](../perf-tests/DRAG_MEASUREMENT.md): drag the first card in
column 1 down past ~15-20 cards over a few seconds, holding at the column's bottom edge long
enough to trigger auto-scroll, then drop — on the same 800-card seeded board.

**First recording, normal browser profile (LastPass + Bitwarden extensions active):** 47.58s
total — Rendering 17,207ms (36%), Scripting 14,638ms (31%), the DevTools Insights panel
auto-flagged "Forced reflow" unprompted. The Bottom-Up tab's top entries (MutationObserver
1,371ms, ResizeObserver 1,184ms) don't correspond to anything in `board.js` — the codebase
has no `ResizeObserver` at all and only two unrelated `MutationObserver` usages (theme/
settings watchers, not the drag path) — so this run was confounded by extension code
reacting to the drag's DOM mutations.

**Second recording, Incognito with extensions disabled, same drag:** **12.57s total** —
Rendering 4,202ms (33%), Scripting collapsed to 366ms (2.9%, from 14,638ms), confirming the
first run's scripting cost was ~97% extension overhead, not AFT code. This second trace is
the one to treat as attributable to AFT. Its Bottom-Up breakdown:

| Function | Self time | % |
|---|---|---|
| **Hit test** | 1,774.8ms | 34.6% |
| Layerize | 1,399.1ms | 27.3% |
| **Layout** | 525.3ms | 10.2% |
| **Paint** | 480.6ms | 9.4% |
| Pre-paint | 357.1ms | 7.0% |
| **Recalculate style** | 146.7ms | 2.9% |
| `formatTooltipDateTime` (`utils.js:248`) | 90.1ms | 1.8% |
| `applyTimeFormat` (`utils.js:77`) | 66.8ms | 1.3% |
| `renderBoard` (`board.js:3373`) | 17.0ms self / 235.9ms total | 4.6% total |

A temporary counter added to `dragover` and the auto-scroll `requestAnimationFrame` loop
(added, measured, then removed — not part of the diff) recorded **1,436 `dragover` events**
and 21 auto-scroll frames for this drag, with our own per-event handler code averaging
0.10ms and peaking at 1.2ms — cheap in isolation. The **Hit test** cost (34.6%, Chrome's
internal cost of resolving which of ~100 draggable elements the pointer is over on every
native `dragover`) and the combined Layout+Paint+Recalculate-style cost (~1.15s, 22.5%) are
the real, browser-attributed costs of firing `dragover` 1,436 times against a ~100-card
column and reordering the DOM on (nearly) every one — this is exactly the item 2.2/1.6/2.1
diagnosis (`getDragAfterElement()`'s per-event, whole-column measurement, and the DOM
mutation it triggers), now with a number: **12.57 seconds for one realistic drag, in a clean
browser, is still broken**, even with extension noise excluded. `renderBoard` appearing in
the trace confirms a full board reload also fired during/after the sequence, compounding the
cost further (item 1.2/1.3).

The `formatTooltipDateTime`/`applyTimeFormat` calls appearing during a drag are a minor,
previously-unnoted finding: something is reformatting card timestamps mid-drag, which
shouldn't be necessary until the drop settles. Not sized into a tier below — small (156ms
combined) relative to the rest — but worth a look alongside item 2.3's incremental-patching
work.

---

## What actually happens when one card changes

Today, moving a single card on column A causes this, for **every** connected client
including the one that made the change:

1. **Client** `PATCH /api/cards/:id` → on success calls `loadBoard()`
   ([board.js:4558](../www/js/board.js#L4558)).
2. **Server** commits, then broadcasts `card_updated` with the full card payload
   ([card_routes.py:1484](../server/card_routes.py#L1484)).
3. **Every client in the room**, including the originator, receives it and calls
   `loadBoard()` ([board.js:719](../www/js/board.js#L719)).
4. `loadBoard()` re-fetches the **entire board** —
   `GET /api/boards/:id/cards` ([board.js:2845](../www/js/board.js#L2845)).
5. **Server** rebuilds the whole board: one card query per column, then a lazy-loaded
   query per card for checklist items and another per card for comments
   ([card_routes.py:389-460](../server/card_routes.py#L389-L460)).
6. **Client** deep-clones the payload via JSON round-trip
   ([board.js:2965](../www/js/board.js#L2965)), then `renderBoard()` throws away the
   entire DOM and rebuilds every card from a template string
   ([board.js:3427](../www/js/board.js#L3427)).
7. `renderBoard()` then runs ~20 whole-document `querySelectorAll` sweeps and attaches
   roughly ten listeners per card ([board.js:3609-3982](../www/js/board.js#L3609-L3982)).
8. A `requestAnimationFrame` pass measures `scrollHeight` on every card and writes a class
   in the same loop ([board.js:3827-3852](../www/js/board.js#L3827-L3852)).
9. `applyPermissionBasedRendering()` runs a further ~15 document-wide sweeps
   ([board.js:4017](../www/js/board.js#L4017)).

The originating client does steps 4-9 **twice**: once from its own success handler, once
from the echo of its own broadcast.

So a one-card change costs, per client, roughly: **~1,600 SQL queries**, a full-board JSON
payload sent uncompressed, a full DOM teardown/rebuild of 800 cards, ~8,000 listener
registrations, and 800 interleaved layout reads/writes. That is the whole story. It is not
one bad line, it is a pipeline with no incremental path in it at any layer.

---

## Tier 1 — Quick wins

Low risk, individually small, no architectural change. Together these should be the
largest single improvement per hour spent. Estimates are developer-days for one person
including tests.

### 1.1 Fix the N+1 on checklist items and comments — **0.25 day**

`get_board_cards` eager-loads only `assigned_to`
([card_routes.py:393](../server/card_routes.py#L393)), then the serialiser walks
`card.checklist_items` ([card_routes.py:443](../server/card_routes.py#L443)) and
`card.comments` ([card_routes.py:453](../server/card_routes.py#L453)). Both relationships
default to lazy `select` ([models.py:131,134](../server/models.py#L131-L134)), so each card
triggers two extra round-trips. 800 cards → ~1,600 queries per board load.

The **public** board endpoint already does this correctly
([board_routes.py:2799-2800](../server/board_routes.py#L2799-L2800)) — copy it:

```python
cards_query = cards_query.options(
    selectinload(Card.assigned_to),
    selectinload(Card.checklist_items),
    selectinload(Card.comments),
)
```

This is the single highest value-to-effort change in the document. It is one line, it has
existing precedent in the same repo, and it turns ~1,600 queries into ~5.

### 1.2 Stop broadcasting a change back to the client that made it — **0.5 day**

`broadcast_event` supports `skip_sid` ([broadcasting.py:51](../server/broadcasting.py#L51)),
and `update_card` passes `getattr(request, "sid", None)`
([card_routes.py:1490](../server/card_routes.py#L1490)) — but `request.sid` only exists
inside Socket.IO event handlers. On an HTTP route it is always `None`, so nothing is ever
skipped. Every actor receives the echo of its own change and does a second full reload.

Fix: have the client send its socket id with mutating requests (an `X-Socket-Id` header set
from `this.websocketManager.socket.id`), read it server-side, and pass it as `skip_sid`.
Apply consistently across the mutating routes, not just `update_card`.

Halves the work for the person actually doing the dragging — which is exactly the person
who notices the lag.

### 1.3 Coalesce rapid `loadBoard()` calls — **0.25 day**

Thirteen socket handlers call `loadBoard()` directly
([board.js:710-803](../www/js/board.js#L710-L803)). A bulk operation such as "move all
cards" or a batch archive emits events that can arrive in a burst, and each one starts a
fresh full-board fetch (the previous one is aborted mid-flight —
[board.js:2795](../www/js/board.js#L2795) — so the work is not just duplicated, it is
wasted).

Add a trailing debounce of ~150ms around a `scheduleBoardReload()` wrapper and point all
socket handlers at it. Keep direct `loadBoard()` for user-initiated view changes where
latency is visible.

Cheap, self-contained, and it caps the damage from every other item in this document.

### 1.4 Enable gzip in nginx — **0.25 day** — ✅ implemented and measured

There was no `gzip` directive anywhere in [server/nginx.conf](../server/nginx.conf). The
board JSON for 800 cards with descriptions and comment bodies is easily several hundred KB,
and `board.js` alone is **358 KB** uncompressed on every cold load.

```nginx
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_min_length 512;
gzip_types application/json application/javascript text/css text/plain image/svg+xml;
```

Added at the top of `server/nginx.conf`, before both `server {}` blocks — `gzip` directives
set at http-context scope (which `conf.d/*.conf` files are included at) apply to every
`server {}` block that includes this file, so one addition covers both the HTTP and HTTPS
server blocks without duplication.

**Measured with `perf-tests/payload_check.py`** (actual bytes transferred, via curl, not the
`requests` library's post-decompression size — `requests` transparently decompresses gzip
responses, which would otherwise hide the real transfer size):

| Response | Uncompressed | Over the wire with gzip | Reduction |
|---|---|---|---|
| Board JSON (800 cards) | 1,800,087 bytes | **69,260 bytes** | **26.0×** |
| `board.js` | 359,800 bytes | 67,584 bytes | 5.3× |
| `board.css` | 50,803 bytes | 8,289 bytes | 6.1× |

The board JSON's real-world wire reduction (26.0×) is somewhat below the offline `gzip -9`
estimate (36.7×, [Baseline measurements](#baseline-measurements) above) because nginx
compresses the response as it streams at `gzip_comp_level 6` rather than buffering the
complete payload and compressing at level 9 — still a very large win, and the right
trade-off, since level 9 spends meaningfully more CPU for a few percent more ratio on
every request.

### 1.5 Drop comment bodies from the board list payload — **0.5 day** — ✅ implemented and measured

The board renderer uses comments for exactly one thing: the count
([board.js:3579-3583](../www/js/board.js#L3579-L3583), was `card.comments.length`, now
`card.comment_count`). Opening a card refetches it in full via `getCardData()` →
`/api/cards/:id` ([board.js:7729](../www/js/board.js#L7729)). Every comment body shipped in
the board payload was therefore pure waste, and `Comment.comment` is a `Text` column
([models.py:253](../server/models.py#L253)) with no length cap.

Replaced the `comments` array with `comment_count` in three server-side serializers that
share the same `renderBoard()` client template and were all found to need the same fix:
`get_board_cards` (`card_routes.py`, the main authenticated board view), the public board
endpoint, and the scheduled-cards view (both in `board_routes.py`) — the latter had no
`selectinload(Card.comments)` at all, so it carried the same N+1 as item 1.1 independently,
now fixed by the same change. `comment_count` is computed as a single grouped
`COUNT(*) ... GROUP BY card_id` query per column rather than by loading and discarding every
comment row. The board export endpoint and the single-card detail endpoints (used when
opening a card) were deliberately left returning full comment bodies — export needs them for
backup fidelity, and the detail view is exactly where a user asked to see them.

This also removed the need to eager-load `Card.comments` in the endpoints above, making
those queries cheaper still (on top of item 1.1's fix).

**Measured**, same 800-card seeded board: uncompressed board payload dropped from
1,800,087 → **1,313,626 bytes (27% smaller)** from removing comment bodies alone; combined
with gzip (item 1.4), the actual bytes over the wire dropped from 69,260 → **48,468 bytes**
(a further 30% on top of gzip's own reduction). On boards with longer comment threads than
this synthetic seed data's two short comments per card, the saving will be considerably
larger — this dataset understates the real-world win.

> **Breaking change, shipped as such.** `/api/boards/:id/cards` and the two related
> board-read endpoints are documented public API. Per project decision (small deploy base,
> tied to a major version release), this ships as an outright breaking response change with
> no transition period — `comments` is gone, not deprecated. **Must be called out in the
> major-version release notes**: any external client reading `card.comments` from these
> three endpoints needs to switch to `card.comment_count` and, if it needs comment bodies,
> fetch them via `GET /api/cards/:id`.

### 1.6 Split the read/write phases in the card-overflow measurement — **0.25 day** — ✅ implemented and measured

Was at [board.js:3867-3881](../www/js/board.js#L3867-L3881) (original, pre-fix line numbers):

```js
document.querySelectorAll('.card').forEach(card => {
  const contentHeight = contentWrapper.scrollHeight;   // READ  → forces layout
  if (contentHeight > collapseHeight) {
    card.classList.add('has-overflow');                // WRITE → invalidates layout
    card.classList.add('collapsed');
  }
});
```

This was textbook layout thrashing: each write invalidates the layout that the next read
then forces the browser to recompute. 800 cards → up to 800 forced synchronous reflows in
one frame.

Fixed by splitting into two passes — collect all overflowing cards first, then apply all
classes in a separate loop (see `renderBoard()` around
[board.js:3853](../www/js/board.js#L3853) for the current version).

**Measured with `perf-tests/browser_probe.py`**, same 800-card board, before/after:

| Metric | Before | After | Change |
|---|---|---|---|
| Forced `Layout` events (one board load) | 806 (median of 3) | **6–19** (3 runs) | **~50-130× fewer** |
| Long-task total time | ~1.3s | 660–830ms | ~40% less |

This was the single highest-value fix measured in this document relative to its size (0.25
day estimated, delivered in well under that) — a two-line reordering eliminated over 99% of
the forced layouts from a board load. Confirmed the collapse/expand toggle still works
correctly end-to-end (all 800 seeded cards correctly detected as overflowing and expand/
collapse still toggles the class).

Superseded later by item 2.4 (skip measuring off-screen cards at all), but this was worth
doing now regardless — it fixes the cost for every card, not just off-screen ones, and cost
under an hour.

### 1.7 Narrow the `transition: all` on cards — **0.1 day** — ✅ implemented

Was at [board.css:592](../www/css/board.css#L592): `transition: all 0.2s` on `.card`. Every
class change on every card — including the `has-overflow` / `collapsed` writes from item
1.6, on all 800 cards at once — engaged the transition machinery for every animatable
property.

Scoped to what `.card.*` state rules in `board.css` actually animate — audited every rule
rather than guessing: `opacity`/`transform` (`.dragging`, `.archived-card`,
`.mobile-touch-drag-source`), `box-shadow` (`:hover`), `border` (`.update-failed`,
`.no-schedule`), `background` (`.archived-card`, `.no-schedule`), `padding-bottom`
(`.card--has-assignee`), `max-width` (`.dragging`) — a wider list than the
`border-color, box-shadow, transform` originally guessed in this doc's first draft, because
`border`, `background`, `padding-bottom`, and `max-width` are also genuinely animated
elsewhere in the file. Verified via `getComputedStyle().transitionProperty` in a real browser
session that all of these are still present after the change — only the blanket `all` is
gone.

Not separately measured — its effect is folded into item 1.6's before/after numbers, since
both changes landed together and layout-thrash count is what this fix targets.

The same pattern (`transition: all`) appears at ~20 other places in `board.css`; the `.card`
rule was the one fixed here because of the element count (up to hundreds of simultaneous
instances), not the others.

### 1.8 Replace the JSON deep clone — **0.1 day** — ✅ implemented

Was at [board.js:2993](../www/js/board.js#L2993):
`this.originalColumns = JSON.parse(JSON.stringify(board.columns))` on every load, purely so
`getColumnCardCount()` ([board.js:3221](../www/js/board.js#L3221)) can count unfiltered
cards in agile mode. That serialised and re-parsed the entire board a second time.

Changed to `structuredClone(board.columns)` — same deep-copy semantics, no
JSON-round-trip. Verified the board still renders all cards correctly and produces no
console errors after the change. Better still (item 2.6, not yet done): have the server
return `total_count` / `done_count` per column and delete `originalColumns` entirely, so no
client-side clone of the whole board is needed at all.

### 1.9 Add a composite index for the card query — **0.25 day** — ✅ implemented and verified

Cards are queried by `column_id` + `scheduled` + `archived`, ordered by `order`
([card_routes.py:391-411](../server/card_routes.py#L391-L411)). The model had separate
single-column indexes on each ([models.py:107-113](../server/models.py#L107-L113)) but no
composite, so MySQL picked one and filtered/sorted the rest.

Added via Alembic migration `035_add_card_column_state_order_index.py` and the matching
`Index(...)` in the `Card` model's `__table_args__`
([models.py](../server/models.py)):

```python
Index('idx_card_column_state_order', 'column_id', 'archived', 'scheduled', 'order')
```

**Verified** with `EXPLAIN` against the seeded 800-card board — the query planner now does an
index range scan directly on `idx_card_column_state_order` for the exact filter+sort pattern
`get_board_cards` runs (`column_id = ? AND archived = ? AND scheduled = ?`, `ORDER BY order`),
with no separate filesort step since the index also satisfies the ordering. Modest at 800
cards, but it is cheap and it scales — this is the kind of fix whose value grows precisely as
board size grows, which is the axis this whole document is about.

**Tier 1 total: ~2.5 developer-days estimated — all 9 items implemented and measured.** See
[Suggested sequencing](#suggested-sequencing) below for the before/after numbers. As
expected, this removed the large majority of server time and payload weight, and a large
slice of client render time, without touching the reload-everything architecture — the board
still fully reloads on every change, it just does so far more cheaply now. The drag
interaction (item 2.2, Tier 2) remains the most visible unfixed cost.

---

## Tier 2 — Strongly recommended, more effort

This tier is where the "moving a card on column B re-renders column A" problem actually
gets fixed. Do Tier 1 first and measure; some of these may look different afterwards.

### 2.1 Event delegation instead of per-element listeners — **1.5 days**

[board.js:3609-3982](../www/js/board.js#L3609-L3982) attaches listeners individually across
~20 `document.querySelectorAll` sweeps: card click, expand button, checklist checkbox,
delete, archive, unarchive, done, move, plus `dragstart`/`dragend` per card in
`setupDragAndDrop()` ([board.js:4267](../www/js/board.js#L4267)). At 800 cards that is
roughly 8,000 listener registrations and 20 full-document traversals **per render**.

Replace with a small number of delegated listeners on `.columns-container`, dispatching on
`e.target.closest('.card-delete-btn')` and friends. Attach once at board init, never again.

There is already a precedent for this pattern in the codebase —
`setupEventDelegation()` at [board.js:169](../www/js/board.js#L169) does exactly this for
checklist items. Follow it.

This is a prerequisite for item 2.3: incremental patching is only cheap if inserting a card
node does not require re-wiring listeners.

### 2.2 Fix the drag hot path — **1 day**

**Measured, not just predicted** — see
[Drag measurement](#drag-measurement-manual-chrome-devtools) above: one realistic drag (down
past ~15-20 cards, holding at the edge for auto-scroll) on the 800-card seeded board took
**12.57 seconds** in a clean browser profile with extensions disabled. 1,436 `dragover`
events fired. Our own per-event handler code is individually cheap (0.10ms average, 1.2ms
worst case — confirmed via temporary instrumentation, not left in the codebase) — the cost
is in what those 1,436 events and their DOM mutations cost the browser: 34.6% "Hit test"
(Chrome resolving which of ~100 draggable elements the pointer is over, every event) plus
~22.5% combined Layout/Paint/Recalculate-style, both scaling with column size and mutation
frequency, neither of which the app currently limits.

On **every** `dragover` event (fires continuously, 60+/sec while dragging):

- [board.js:4419](../www/js/board.js#L4419) `getDragAfterElement()` calls
  `getBoundingClientRect()` on **every non-dragging card in the column**;
- the handler then immediately inserts the dragged node into the DOM
  ([board.js:4352-4364](../www/js/board.js#L4352-L4364)), invalidating layout;
- so the next event's rect reads force a full reflow again;
- and the DOM mutation itself is what feeds the browser's "Hit test" cost on the next event —
  the app doesn't control that part directly, but reducing *how often* it mutates the DOM
  (throttling) reduces how often the browser has to pay it.

This is the single biggest contributor to the "dragging feels awful" symptom, and it is
entirely independent of the reload problem.

Fix:
- Snapshot the card rects once at `dragstart` into a sorted array of midpoints.
- Binary-search that array in `dragover` instead of measuring.
- Recompute the snapshot only when the placeholder actually moves.
- Throttle the `dragover` handler to one `requestAnimationFrame` — this is the part that
  should most directly cut the "Hit test" cost too, since it reduces how many times the
  browser dispatches `dragover` against the column in the first place.

Re-measure with the same manual procedure after this fix lands — the 12.57s number is the
"before" to beat.

`getDropOrderValue()` ([board.js:4434](../www/js/board.js#L4434)) does a similar full
`querySelectorAll` + `indexOf` walk, but only on drop, so it matters far less.

### 2.3 Incremental DOM patching for card-level events — **3-4 days**

This is the core fix for the reported symptom.

The broadcasts **already carry everything needed**: `card_updated` sends the full
`card_data` ([card_routes.py:1484](../server/card_routes.py#L1484)), as do `card_created`
([card_routes.py:722](../server/card_routes.py#L722)) and `card_archived`
([card_routes.py:1840](../server/card_routes.py#L1840)). The client receives this payload
and **throws it away** in favour of refetching the whole board.

Build a `renderCard(cardData)` function returning a single detached card element — this
means extracting the per-card block at
[board.js:3519-3587](../www/js/board.js#L3519-L3587) out of the giant template literal,
which is worth doing on its own merits — then:

| Event | New behaviour |
|---|---|
| `card_updated` (no move) | Replace one card node; update column counts |
| `card_updated` (moved) | Move the existing node; update both columns' counts |
| `card_created` | Insert one node at the right index |
| `card_deleted` | Remove one node (already partly done — [board.js:723](../www/js/board.js#L723)) |
| `card_archived` / `card_unarchived` | Remove or insert one node |
| `checklist_item_*` | Patch the checklist block of one card |
| `column_*`, `cards_moved` | Keep the full `loadBoard()` — structural and rare |

Keep `loadBoard()` as the fallback for anything unrecognised, on reconnect, and on any
consistency check failure. The goal is not to eliminate full reloads, it is to stop using
them for the 95% case.

Do 2.1 first — patching a node in is only cheap if listeners are delegated.

### 2.4 Lazy overflow measurement via IntersectionObserver — **0.5 day**

Supersedes item 1.6. Instead of measuring all 800 cards up front, use an
`IntersectionObserver` to measure and classify each card the first time it scrolls into
view, then `unobserve` it. Off-screen cards are never measured.

This also unblocks item 2.5, which is otherwise incompatible with the eager measurement
pass.

### 2.5 `content-visibility` on cards — **0.5 day**

`.column-cards` is a scrolling flex container ([board.css:547](../www/css/board.css#L547))
with no containment hints, so the browser lays out and paints all 100 cards in a column even
though ~10 are visible.

```css
.card {
  content-visibility: auto;
  contain-intrinsic-size: auto 120px;
}
```

This gives most of the benefit of virtualisation (item 3.1) for a fraction of the cost and
with none of the drag-and-drop complications.

**Caveat, and the reason this is Tier 2 rather than Tier 1:** `content-visibility: auto`
makes `scrollHeight` return 0 for skipped off-screen elements, which breaks the
overflow-detection pass at [board.js:3845](../www/js/board.js#L3845). **Item 2.4 must land
first.** Also verify against the scroll-restoration logic
([board.js:1602](../www/js/board.js#L1602)) and the `contain-intrinsic-size` estimate, since
a bad estimate causes scrollbar jitter.

### 2.6 Return card counts from the server — **0.5 day**

Add `card_count` / `done_count` / `total_active_count` per column in `get_board_cards`
(grouped `COUNT(*)`, not by loading rows). Lets the client delete `originalColumns` (item
1.8) and, more importantly, means an incremental update can adjust a column header without
holding a full unfiltered mirror of the board in memory.

### 2.7 Push the done/not-done filter into the query — **0.5 day**

`processBoard()` downloads every card then filters in JS
([board.js:2973-2987](../www/js/board.js#L2973-L2987)) for agile boards. On a board where
most cards are done, the task view downloads and discards the majority of the payload. The
public endpoint already accepts a `done` query param
([board_routes.py:2793](../server/board_routes.py#L2793)) — mirror it on the authenticated
endpoint. Depends on 2.6 for the counts, which is why it is not in Tier 1.

### 2.8 Bulk UPDATE for move-all-cards — **0.5 day**

[card_routes.py:969-989](../server/card_routes.py#L969-L989) reassigns `card.order` in a
Python loop over ORM instances, producing one UPDATE per row on flush. Moving 100 cards into
a column of 100 issues ~200 statements. Replace with two bulk
`.update({...}, synchronize_session=False)` calls, as the reorder path at
[card_routes.py:1422-1455](../server/card_routes.py#L1422-L1455) already does.

**Tier 2 total: ~8-9 developer-days.**

---

## Tier 3 — High ceiling, high effort

Worth planning for, not worth starting before Tier 1 and 2 are measured.

### 3.1 Virtualised column rendering — **5-8 days**

Render only the cards in (and near) the viewport, recycling nodes on scroll. The only
approach that makes 1,000+ card columns genuinely fast.

Significant complications, all of which are real in this codebase:
- Native HTML5 drag-and-drop ([board.js:4266](../www/js/board.js#L4266)) assumes every card
  is a live DOM node; dragging past the window edge needs the auto-scroll logic
  ([board.js:4208](../www/js/board.js#L4208)) to materialise rows on demand.
- Card heights are variable and only known after measurement (item 2.4).
- Per-column scroll restoration ([board.js:1602](../www/js/board.js#L1602)) and expanded-card
  state ([board.js:1627](../www/js/board.js#L1627)) both assume a stable full DOM.
- Ctrl-F / browser text search stops finding off-screen cards, which is a real UX
  regression on a board tool.

**Do item 2.5 first and measure.** `content-visibility` may well close enough of the gap
that this never needs building.

### 3.2 Fractional ordering (lexorank) — **4-5 days**

Moving a card to the top of a 100-card column currently rewrites the `order` of every card
below it ([card_routes.py:1417-1456](../server/card_routes.py#L1417-L1456)) — O(n) row
writes per move, plus lock contention on a busy board. Fractional or lexorank ordering
makes it O(1) by inserting a value between neighbours.

Needs: schema migration (`order` → string or float), a rebalancing job for when precision
runs out, a data migration for existing boards, and updates to every ordering path
(import, move-all, archive-after, scheduler). High risk relative to the win at current
scale — the O(n) write is not what users are feeling today; the O(n) *render* is.

### 3.3 Delta endpoint — **3 days**

`GET /api/boards/:id/cards?since=<timestamp>` returning only cards changed since. Makes
reconnect resync cheap instead of a full reload, and gives item 2.3 a correct recovery path
after a dropped WebSocket. Requires a reliable `updated_at` on every mutation path (several
currently set it conditionally — see `user_content_changed` at
[card_routes.py:1460](../server/card_routes.py#L1460)) and a tombstone strategy for
deletions.

### 3.4 ETag / `If-None-Match` on the board endpoint — **1.5 days**

Lets an unchanged board load return `304` with no body. Helps tab-switching and the
debounced-reload case, but note it does **not** help the main complaint: after a change,
the ETag differs by definition. Genuine but narrow value.

### 3.5 Modularise `board.js` — **5+ days, ongoing**

358 KB and ~9,000 lines in one file, with `renderBoard()` alone spanning 640 lines
([board.js:3373-4015](../www/js/board.js#L3373-L4015)). This is primarily a maintainability
problem, but there is a real performance component: 358 KB of uncompressed JS must be
parsed and compiled on every cold load, which is very noticeable on mobile. Item 1.4 (gzip)
addresses the transfer cost but not the parse cost.

Extracting the render layer is a natural by-product of item 2.3 and should be done
opportunistically alongside it rather than as a standalone project.

---

## Tier 4 — Considered and not recommended

Documented so they are not re-proposed later.

**Rewrite the board in React/Vue/Svelte.** The real win a framework offers here is keyed
diffing — which is precisely what items 2.1 and 2.3 deliver, at ~10 days instead of ~40,
without a build toolchain, and without discarding the accessibility, permission, theming,
and drag-and-drop behaviour already working in the current code. Revisit only if the UI is
being rewritten for other reasons.

**Redis cache of the serialised board.** Redis is already in the stack, so it is tempting.
But invalidation on a board that mutates this frequently is nearly the same complexity as
the delta endpoint (3.3) with worse failure modes, and once item 1.1 lands, the query cost
this would cache is largely gone. Caching a fast query is not a win.

**Server-side rendering of card HTML fragments.** Would cut client render time, but
reintroduces HTML-string assembly on the server, directly against the DOM-node-construction
approach adopted deliberately for XSS resistance
([AGENT_CONTEXT.md](../AGENT_CONTEXT.md), `notifications.js`), and couples the API to the
markup — which the README explicitly positions as replaceable.

**Parse board JSON in a Web Worker.** The bottleneck is DOM construction and layout, not
`JSON.parse`. Moving parsing off-thread adds a structured-clone copy back and buys nothing
measurable.

**Paginate cards within a column ("load more").** Cheaper than virtualisation but changes
the UX — a Kanban column that does not show all its cards is not really a Kanban column, and
it breaks drag-to-position for anything past the first page. Item 2.5 gives a comparable win
with no UX change.

**HTTP/2 server push / preconnect for the board payload.** One request, already in flight
immediately. Nothing to gain.

---

## Suggested sequencing

| Step | Items | Effort | Expected effect |
|---|---|---|---|
| 0 | Baseline measurements | 0.5 day | Makes everything below provable |
| 1 | All of Tier 1 | 2.5 days | ✅ Done — see results below |
| 2 | Re-measure | 0.5 day | ✅ Done — see results below |
| 3 | 2.2 (drag hot path) | 1 day | Fixes drag jank specifically — highest-visibility single fix |
| 4 | 2.1 (delegation) → 2.4 → 2.5 | 2.5 days | Render cost stops scaling with total card count |
| 5 | 2.6, 2.7, 2.8 | 1.5 days | Payload and write-path cleanup |
| 6 | 2.3 (incremental patching) | 3-4 days | Cross-column updates stop re-rendering everything |
| 7 | Re-measure, then decide on Tier 3 | — | 3.1 and 3.2 may prove unnecessary |

### Step 1-2 results: Tier 1 complete, before/after

All nine Tier 1 items landed together on this branch. Re-measured with the identical
harness and the identical 800-card seeded board used for the baseline:

| Metric | Before (baseline) | After Tier 1 | Change |
|---|---|---|---|
| `GET /api/boards/:id/cards` server time | 902.5ms | **101.7ms** | **8.9× faster** |
| SQL queries per request | 1,622 | **38** | **43× fewer** |
| Client-observed round trip | 910.1ms | **118.9ms** | **7.7× faster** |
| Response payload (uncompressed) | 1,800,087 bytes | 1,313,626 bytes | 27% smaller |
| Response payload (actual bytes over the wire, gzip'd) | not compressed | **48,491 bytes** | **37.1× smaller** |
| Forced `Layout` events (one board load) | 806 | **17** (median of 3) | **~47× fewer** |
| Long-task total time | ~1,325ms | 672ms | 49% less |

Raw data in [perf-tests/results/](../perf-tests/results/) (`baseline-tier0` and
`after-tier1` labels); running history in
[perf-tests/results/history.md](../perf-tests/results/history.md).

The 38 remaining queries is close to the theoretical floor for 8 columns with
`selectinload`-batched relationships (roughly 1 board query + 1 column query + a handful of
board-metadata queries + up to 3 batched relationship queries per column) — there isn't much
further to squeeze out of query count without changing the endpoint's shape (Tier 2 items
2.6/2.7 go in that direction). Server time and payload are now solidly in "feels instant"
territory; the remaining, most visible cost is the drag interaction (item 2.2, not yet
measured post-fix — see [Drag measurement](#drag-measurement-manual-chrome-devtools) above
for the pre-fix 12.57s baseline).

Steps 1 and 3 together should account for the large majority of the perceived improvement —
step 1 is now done and measured; step 3 (drag hot path) remains the next highest-leverage
piece of work.

---

## Measuring it

Done — see [Baseline measurements](#baseline-measurements) above and
[perf-tests/](../perf-tests/), which is now a standing, reusable module (not a one-off
script) rather than something to build per-change. It covers everything originally proposed
here:

- **Seed data**: [perf-tests/seed_board.py](../perf-tests/seed_board.py) creates a large
  board via the real `POST /api/boards/import` native-JSON path (not direct DB writes),
  parameterised by columns/cards/checklist-items/comments.
- **Server query count + timing**: [server/_perf_probe.py](../server/_perf_probe.py), a
  SQLAlchemy `before_cursor_execute` counter gated behind `PERF_PROBE=1` (zero cost
  otherwise), read back by [perf-tests/api_probe.py](../perf-tests/api_probe.py).
- **Payload / gzip**: [perf-tests/payload_check.py](../perf-tests/payload_check.py) — also
  reports whether nginx is *actually* serving compressed responses, not just what gzip
  could achieve.
- **Client render cost**: [perf-tests/browser_probe.py](../perf-tests/browser_probe.py) —
  Playwright + a raw Chrome DevTools Protocol trace of a full board load, summarised to
  layout count, scripting time, and long-task count.
- **Card-drag cost**: could not be automated reliably (see
  [Baseline measurements](#baseline-measurements) above) —
  [perf-tests/DRAG_MEASUREMENT.md](../perf-tests/DRAG_MEASUREMENT.md) is a ~3 minute manual
  Chrome DevTools procedure instead.

Run `perf-tests/run_all.py --board-id <id> --label <tag>` after each tier lands; it appends
a row to [perf-tests/results/history.md](../perf-tests/results/history.md) so before/after
numbers sit side by side without manual bookkeeping. See
[perf-tests/README.md](../perf-tests/README.md) for full usage.

**Regression guard.** `ui-tests/` already runs Playwright against the live stack
([ui-tests/docs/UI_TESTING.md](../ui-tests/docs/UI_TESTING.md)). Once Tier 1 lands and a
post-Tier-1 baseline is recorded, consider adding a `ui-tests/` case that seeds a large board
and asserts the board-load query count or payload size stays under a threshold with generous
headroom — the goal is catching a 10× regression, not policing 20% noise on CI hardware. Not
done yet; `perf-tests/` is currently a manual/on-demand tool, not part of CI.

---

## Release notes — what to call out for this major version

Tier 1 shipped on this branch. Two items need to be in the upgrade-facing release notes;
everything else in Tier 1 is an internal performance change with no visible behaviour
change and doesn't need a release-notes mention.

1. **Breaking API change (item 1.5).** `GET /api/boards/:id/cards`,
   `GET /api/public/boards/:slug`, and `GET /api/boards/:id/cards/scheduled` no longer return
   a `comments` array on each card — only `comment_count` (an integer). Any external
   integration reading `card.comments` from these three endpoints will get `undefined`/a
   `KeyError` where it used to get an array, and needs to switch to `comment_count`, or fetch
   full comment bodies via `GET /api/cards/:id` (unchanged, still returns full `comments`).
   No transition period — ships as a hard break, per project decision (small deploy base,
   tied to this major version).

2. **Performance improvement, worth a line even though nothing breaks.** Board loads and
   updates are substantially faster on large boards (100+ cards per column) — roughly 9×
   faster server response, 43× fewer database queries, and dramatically less UI jank
   (forced layout recalculations cut ~47×) on an 800-card test board. Worth mentioning
   because it directly addresses a real, reported pain point (issue #523) — users who
   avoided large boards because of lag should be told it's fixed.

Not release-notes-worthy but worth knowing about: item 1.2's WebSocket `skip_sid` fix
happened to also fix the `delete_card` `DetachedInstanceError` risk tracked in
[issue #524](https://github.com/sjefferson99/aft/issues/524) (touching the same lines for
skip_sid meant capturing `column_id` before delete in the same edit, matching the existing
`board_id` pattern in that function) — that issue can be closed as fixed by this PR rather
than needing separate work.

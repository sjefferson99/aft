# Feature: Board Text Search and Header Space Optimization

Status: Ready for implementation

## Overview

Add text search to board.html that filters board cards by:
- Card title
- Card description
- Checklist item text

Add special card reference matching:
- Unquoted input pattern #123 must match card id 123 only
- Quoted input "#123" must be treated as text search only (no card id match)

Search should run after a 500ms typing pause, and be available:
- In the header (desktop and mobile)
- Inside the board filter panel (next to existing assignee filters)

Minimum search length for execution is 2 characters (for example #1 is valid).

Search input must expose a hover/focus tooltip that documents query grammar:
- Spaces are AND
- Commas are OR
- Double quotes create exact phrases
- Repeated double quotes inside quoted phrases escape a literal quote

The search control should include a trailing button that opens the filter panel. This replaces the current header settings menu entry used to toggle filters.

A clear text X icon should be available in the search field to reset the text search easily.

To make room in the header, compress the status widget to a health dot when healthy. Full status details (Connected/version/more info) move to a tooltip on hover. If an error state appears, the widget expands and shows full text immediately.

This document defines:
- MVP (MySQL-backed, board-level filtering)
- Future enhancements (better stemming/synonyms/relevance)
- A tracked implementation checklist

---

## Goals

- Add responsive search UX on board page with 500ms debounce.
- Support card id reference search via #<number> patterns.
- Keep assignee filters and text search working together.
- Perform filtering server-side via existing board card GET endpoints.
- Add indexes to support acceptable search performance.
- Preserve current authorization and board visibility constraints.
- Keep current behavior for journal comments/notes (excluded from search for now).
- Keep search behavior identical across task, done, and archived board views.

## Non-Goals (MVP)

- Search across all boards from a global view.
- Journal note/comment search.
- Full semantic search / vector search / RAG.
- Perfect stemming/lemmatization/synonyms.

---

## Current Architecture Notes

- Board data is loaded primarily from:
  - GET /api/boards/<board_id>/cards
  - GET /api/boards/<board_id>/cards/scheduled (scheduled view)
- Existing assignee filters are already passed as query parameters and applied server-side.
- Existing board filter visibility is coordinated via custom window events between header.js and board.js.
- Status widget is implemented in shared header component and updated via periodic health checks in header.js.

This makes text search a good fit for:
- Query parameter extension on existing endpoints
- BoardManager query builder extension in board.js
- Shared header control + board-level event wiring

---

## Proposed MVP Design

### 1) API and backend filtering

Add an optional query parameter to relevant board card endpoints:
- q: string (search query)

Apply search in:
- GET /api/boards/<board_id>/cards
- GET /api/boards/<board_id>/cards/scheduled

Optional follow-up (not required for board.html MVP):
- Public board endpoint parity, if/when public board needs search.

Search scope per card:
- cards.title
- cards.description
- checklist_items.name via card relationship

Search semantics (MVP):
- Case-insensitive
- Token grammar:
  - Space-separated terms are AND
  - Comma-separated terms are OR
  - Double-quoted terms are exact phrases
  - Commas inside double quotes are treated as literal characters, not OR separators
  - Repeated double quotes inside a quoted phrase escape a literal quote
- Card reference behavior:
  - An unquoted token matching #[1-9][0-9]* must match cards where card.id equals the parsed number
  - Unquoted #<number> tokens are id-only matches (do not also perform text matching)
  - A quoted token "#<number>" is text-only matching (does not perform card id matching)
  - Tokens with leading-zero numerics (for example #00379) are treated as normal text tokens only
  - Tokens with non-numeric hash content (for example #abc, ##123) are treated as normal text tokens only
- Ignore empty/whitespace-only input
- Require at least 2 characters before issuing search requests

Implementation approach (MVP-safe):
- Use SQLAlchemy expression with joined checklist_items and OR over fields.
- Distinct cards to avoid duplicate rows when multiple checklist items match.
- Continue applying assignee filters + archived/scheduled filters + permissions exactly as today.
- Parse query into OR groups and AND terms per group before SQL predicate build.
- Apply the same search predicate path for task, done, and archived view endpoints/parameters.

### 2) Database indexes

Add migration with MySQL-first indexing strategy:

Phase A (low risk, immediate):
- Ensure cards.title indexed pattern support where possible.
- Ensure cards.description is indexed appropriately for fulltext use.
- Add fulltext index on cards(title, description).
- Add fulltext index on checklist_items(name).

Phase B (if query plan still poor):
- Add helper generated column(s) or denormalized search text with trigger/update path.
- Re-evaluate execution plans against realistic board sizes.

Note: checklist_items search across many rows may require careful join strategy and may benefit from EXISTS subqueries to avoid row explosion.

### 3) Frontend behaviour on board page

Add board-level search state in BoardManager:
- searchQueryRaw
- searchQueryDebounced
- searchDebounceTimer (500ms)

When debounced value changes:
- Reload board through existing loadBoard flow.
- Append q parameter with existing assignee parameters.

Display behavior:
- Search input in header on board page (desktop and mobile).
- Search input in filter panel near assignee filters.
- Two controls stay in sync.
- Clear action resets q and reloads board.
- Mobile search is always available; initial implementation may use icon-to-expand while remaining always reachable.
- Header/mobile search control includes a tooltip on hover/focus that explains grammar and examples.

### 4) Filter panel launch button from search bar

Header search control includes trailing filter icon/button:
- Click dispatches existing board filter toggle event.
- Remove or hide settings-menu filter toggle entry on board page.
- Preserve clear filters action behavior.

### 5) Header status widget compression

Healthy state:
- Show only green status dot.
- Tooltip includes:
  - Connected status
  - Version info
  - More info hint/link behavior

Unhealthy states (server/db/websocket/service unhealthy):
- Expand widget to text + details for visibility.
- Keep existing color semantics.

Accessibility:
- Tooltip info also available via aria-label/title.
- No status information should be hover-only for keyboard users.

---

## MySQL capability and limitations (for this feature)

What MySQL gives out-of-box:
- FULLTEXT indexes (InnoDB)
- Natural language mode, boolean mode, optional query expansion
- Tokenization, stopword filtering, minimum token length constraints

Important limitation for requested "start/starts/started" style matching:
- Native MySQL FULLTEXT does not provide robust stemming/lemmatization like dedicated search engines.
- Boolean prefix search supports start* style matches, but not full linguistic normalization.

Practical MVP expectation:
- Strong keyword matching with prefix support where enabled.
- Limited morphology handling compared to PostgreSQL + dictionaries or dedicated search engines.

Recommendation:
- Keep MySQL for MVP.
- Instrument search quality/performance.
- Revisit PostgreSQL or dedicated search backend once usage data justifies it.

---

## Future Search Enhancements (Later Phases)

### Option 1: Enhanced PostgreSQL text search

Potential gains:
- Better stemming via language dictionaries
- Trigram similarity (pg_trgm) for typo tolerance
- Weighted ranking across title/description/checklist

Suggested path:
- Add repository-level search abstraction first (query builder/service layer).
- Then support MySQL and Postgres strategies behind one API contract.

### Option 2: Dedicated search engine

Candidates:
- Meilisearch (simple relevance/synonyms/typo tolerance)
- OpenSearch/Elasticsearch (more powerful, higher ops overhead)

Potential gains:
- Synonyms
- Typo tolerance
- Better ranking
- Highlighting/snippets

Tradeoff:
- Additional infra and sync complexity.

### Option 3: Hybrid

- Keep DB filtering for strict filters (board, assignee, archived).
- Use search engine only for text matching + ranked IDs.
- Fetch authorized records from DB by returned IDs.

---

## Delivery Plan and Checklist

## Phase 0: Alignment and guardrails
- [x] Confirm q parameter contract and empty-query behavior.
- [x] Confirm MVP semantics:
  - [x] Spaces = AND
  - [x] Commas = OR
  - [x] Double quotes = exact phrase
  - [x] Repeated double quotes escape literal quotes in quoted phrases
- [x] Confirm hash behavior:
  - [x] Unquoted #<digits> is id-only
  - [x] Quoted "#<digits>" is text-only
  - [x] Leading-zero and non-numeric hash tokens stay text-only
- [x] Confirm minimum execution length is 2 characters.
- [x] Confirm done and archived views use identical search behavior.
- [x] Confirm mobile search is always present (icon-expand allowed for layout).
- [x] Enforce backend q contract:
  - [x] Max query length 200 characters
  - [x] Max comma-separated OR groups 12
  - [x] Max total terms 24
  - [x] Max individual term length 80 characters
  - [x] Invalid q returns HTTP 400 with a clear validation message

## Phase 1: Backend API + query implementation
- [x] Add q parsing and validation in board card endpoints.
- [x] Add tokenizer/parser for spaces, commas, quoted phrases, and escaped quotes.
- [x] Add text search predicates for title/description/checklist.
- [x] Add strict #<digits> card id predicate support for unquoted tokens.
- [x] Ensure quoted "#<digits>" stays text-only.
- [x] Keep existing assignee/archived/scheduled/permission filters intact.
- [x] Ensure same predicate logic is used for task, done, and archived result views.
- [x] Add/extend endpoint docstrings for new parameter.
- [x] Run targeted API tests for new parser and predicate behavior before phase sign-off.
- [x] Run a build/smoke check after endpoint changes and capture results in this doc.

### Phase 1 Validation Notes (2026-05-31)

- Backend implementation:
  - Added shared parser and predicate helpers in `server/board_routes.py` and applied them to:
    - `GET /api/boards/<board_id>/cards`
    - `GET /api/boards/<board_id>/cards/scheduled`
  - Search grammar implemented for spaces (AND), commas (OR), quoted phrases, and repeated double-quote escaping inside quoted phrases.
  - Unquoted `#<digits>` tokens map to strict `card.id` matching only; quoted `"#<digits>"` remains text-only.
  - Tokens like `#00379`, `#abc`, `##123` remain text tokens.

- Tests executed:
  - Command:
    - `..\\.venv\\Scripts\\python.exe -m pytest tests/test_api_cards.py tests/test_api_boards.py -k "text_search or filter_by_assignees_and_unassigned or includes_secondary_assignees_when_enabled" -v`
  - Result:
    - `8 passed, 95 deselected`

- Build/smoke checks:
  - `docker compose up -d --build server` completed successfully.
  - `docker compose up -d nginx` restored API ingress for integration tests.
  - `docker compose ps` healthy state observed for `db`, `redis`, `server`, and `nginx` containers.
  - Startup log verification shows Gunicorn workers booting cleanly with no traceback.

## Phase 2: Database migration + indexes
- [x] Add Alembic migration for search indexes.
- [x] Verify migration idempotency and rollback path.
- [x] Validate query plans on representative data volume.
- [x] Run migration + rollback test build in local/dev compose environment.
- [x] Re-run affected API tests after migration application.

### Phase 2 Validation Notes (2026-05-31)

- Migration implemented:
  - Added `server/alembic/versions/032_add_text_search_fulltext_indexes.py`.
  - Upgrade adds:
    - `idx_cards_fulltext_title_description` on `cards(title, description)`
    - `idx_checklist_items_fulltext_name` on `checklist_items(name)`
  - Downgrade drops both indexes.

- Migration verification:
  - Alembic history shows `031 -> 032 (head)`.
  - Executed migration lifecycle checks:
    - `alembic upgrade head`
    - `alembic downgrade -1`
    - `alembic upgrade head`
    - `alembic upgrade head` (no-op idempotency check)
  - Final revision confirmed at `032 (head)`.

- DB-level index/query checks:
  - `SHOW INDEX` confirms both FULLTEXT indexes exist.
  - `EXPLAIN ... MATCH(title, description) AGAINST (...)` shows full-text index search using `idx_cards_fulltext_title_description`.
  - `EXPLAIN ... title LIKE '%alpha%'` still shows table scan (expected for leading-wildcard LIKE).
  - Representative-volume run (temporary seeded 5,000-card board, then cleaned up):
    - `LIKE` query (`title/description LIKE '%alpha%'`): table scan, ~1.98 ms, 33 rows.
    - `MATCH ... AGAINST ('alpha')`: full-text index search, ~0.09 ms, 33 rows.
    - Cleanup verified (`cleanup_remaining_boards=0`).

- Compose/build checks:
  - `docker compose up -d --build server` successful.
  - Stack healthy after migration tests (`db`, `redis`, `server`, `nginx`).

- API regression checks after migration:
  - Re-ran affected board text-search tests.
  - Result: `8 passed, 95 deselected`.



## Phase 3: Frontend search controls and sync
- [x] Add header search control for board page (desktop + mobile).
- [x] Add search control to board filter bar UI.
- [x] Add 500ms debounce and board reload wiring in board.js.
- [x] Keep search value synchronized between both controls.
- [x] Add clear behavior and active-filter indicator integration.
- [x] Add hover/focus tooltip describing AND/OR/quotes/escaped-quote behavior.
- [x] Enforce minimum 2-character trigger (with #1 explicitly valid).
- [x] Verify same search experience in task, done, and archived views.
- [x] Run frontend build/smoke checks and board interaction tests for this phase.

### Phase 3 Validation Notes (2026-05-31)

- Frontend implementation:
  - Added header search control in `www/components/header.html` (desktop/mobile responsive in existing header layout).
  - Added reusable header search styles and tooltip behavior in `www/css/header.css`.
  - Added filter-panel search control and styling near assignee filters in `www/js/board.js` and `www/css/board.css`.
  - Added board-level search state and synchronization in `www/js/board.js`:
    - `searchQueryRaw`, `searchQueryDebounced`, 500ms debounce timer.
    - Query wiring to existing card endpoints through `q` parameter.
    - 2-character minimum gate before requests are sent.
    - Shared clear behavior and active-filter indicator integration.
    - Search integrated into existing filter clear flow.
  - Initial `q` value now hydrates from URL query params on board page load.

- Static validation:
  - VS Code diagnostics check reports no errors in changed files:
    - `www/js/board.js`
    - `www/components/header.html`
    - `www/css/header.css`
    - `www/css/board.css`

- Compose/frontend smoke:
  - Command executed:
    - `docker compose up -d --build nginx ; docker compose ps`
  - Result:
    - `nginx`, `server`, `db`, and `redis` containers up; `server` and `redis` healthy.

- Browser interaction checks (authenticated):
  - Logged in successfully via `/login.html` and navigated to an accessible board.
  - Verified header search control is present and shows grammar tooltip.
  - Enabled filter panel and verified filter-bar search control appears with matching tooltip.
  - Verified control synchronization in both directions (header <-> filter panel).
  - Verified min-length gate behavior:
    - 1-character query (`a`) does not activate filter state.
    - 2-character query (`ab`) activates filter state and shows filter-active indicator.
  - Verified clear-button behavior resets both controls and clears active-filter state.

## Phase 4: Filter button and settings menu changes
- [x] Add filter-panel toggle button at end of search input.
- [x] Remove/replace board filter toggle item from settings menu.
- [x] Keep clear filters entry as-is or move if needed.
- [x] Run UI regression checks for header menus and mobile drawer interactions.

### Phase 4 Validation Notes (2026-05-31)

- Header search action:
  - Added trailing filter icon button in `www/components/header.html`.
  - Button dispatches a dedicated open-filters event path in `www/js/board.js` (`boardFiltersShowRequested`) so the panel opens predictably.

- Settings menu cleanup:
  - Removed board filter toggle entries from settings menus (desktop + mobile) in `www/components/header.html`.
  - Kept existing clear-filters entries unchanged.

- UI behavior/regression checks:
  - Verified filter panel can be opened from the new header search filter button.
  - Verified settings menu no longer shows "Show/Hide Filters" entries.
  - Verified clear-filters visibility still follows active filter state.

## Phase 5: Status widget compact mode
- [x] Healthy state renders dot-only with accessible tooltip.
- [x] Error states auto-expand with full status text.
- [x] Mobile behavior remains clean and non-overlapping.
- [x] Run accessibility and responsive smoke checks for tooltip and expanded error modes.

### Phase 5 Validation Notes (2026-05-31)

- Implementation:
  - Added status widget presentation logic in `www/js/header.js`:
    - Healthy (`.status-icon.success`) now applies compact dot-only mode.
    - Non-healthy states automatically revert to expanded text/details mode.
    - Tooltip/accessible label now includes status, version info, and a "More info" hint.
    - Added keyboard activation for the widget (`Enter`/`Space`) to preserve navigability to System Info.
  - Added compact mode styles in `www/css/header.css` using `.db-status.status-compact`.

- Accessibility/responsive smoke:
  - Verified compact mode exposes status details through `title` and `aria-label` on the widget.
  - Verified error class/text immediately expands the widget (dot + text/details visible).
  - Verified mobile behavior remains clean with existing mobile breakpoint rule that hides `.db-status`.

## Phase 6: Consolidated validation and documentation
- [x] Confirm each phase-level test/build gate completed and recorded.
- [x] Add/finish API tests for:
  - [x] q filtering (title/description/checklist)
  - [x] spaces AND behavior
  - [x] commas OR behavior
  - [x] quoted phrase behavior
  - [x] escaped quote behavior using repeated double quotes
  - [x] unquoted #<digits> id-only matching
  - [x] quoted "#<digits>" text-only matching
  - [x] leading-zero and non-numeric hash tokens text-only matching
  - [x] combined q + assignee filters
  - [x] empty/no-result/min-length behavior
- [x] Add UI test coverage for debounce + control sync behavior (if framework allows).
- [x] Manual perf pass on realistic board size.
- [x] Update user docs for board search behavior and limitations.
- [x] Record post-MVP improvements from Future Search Enhancements section.

### Phase 6 Validation Notes (2026-05-31)

- Consolidated test/build gates:
  - Rebuilt local stack from clean DB state to validate in a deterministic environment:
    - `docker compose down ; Remove-Item -Recurse -Force data ; docker compose up -d --build`
  - Rebuilt frontend artifacts after final UI changes:
    - `docker compose up -d --build nginx`

- API test coverage completion:
  - Added missing assertions/tests in `server/tests/test_api_cards.py` for:
    - non-numeric double-hash token behavior (`##123` remains text-only)
    - empty/whitespace query behavior (ignored; baseline result set unchanged)
    - explicit no-result query behavior (returns empty card set)
  - Executed focused API suite:
    - `..\\.venv\\Scripts\\python.exe -m pytest server/tests/test_api_cards.py server/tests/test_api_boards.py -k "text_search or filter_by_assignees_and_unassigned or includes_secondary_assignees_when_enabled" -v`
  - Result:
    - `9 passed, 95 deselected`

- UI debounce/control-sync coverage:
  - No dedicated committed UI test framework is currently wired for this feature path.
  - Completed scripted browser smoke validation of debounce, cross-control sync, tooltip behavior, filter toggle behavior, and compact/expanded status widget behavior during Phases 3-5.

- Performance validation:
  - Reused representative-volume perf run from Phase 2 (5,000-card seeded board) and recorded results there:
    - `LIKE` search: ~1.98 ms (table scan)
    - `MATCH ... AGAINST` search: ~0.09 ms (FULLTEXT index)

- User documentation updates:
  - Updated `README.md` board feature section with:
    - board text-search grammar and behavior
    - card-id hash-token semantics
    - header filter icon workflow for opening/toggling filter panel

- Post-MVP improvements captured from roadmap:
  - Add repository-level search abstraction to support pluggable backends.
  - Evaluate PostgreSQL text-search enhancements (`pg_trgm`, weighted ranking, stemming dictionaries).
  - Evaluate dedicated search engine path (Meilisearch/OpenSearch) for synonyms/typo tolerance/ranking.
  - Consider hybrid model (DB filters + search-engine ranked IDs) for larger deployments.

---

## Suggested Acceptance Criteria (MVP)

- Typing in search field filters cards after ~500ms pause.
- Search requires 2+ characters before request execution.
- Matching in title, description, and checklist item text is included.
- Entering #379 matches card id 379 only.
- Entering "#379" performs text search only.
- Entering #00379 is treated as plain text search only (no id match).
- Entering #abc or ##123 is treated as plain text search only (no id match).
- Search grammar works as specified:
  - Spaces are AND
  - Commas are OR
  - Quoted phrases are exact
  - Repeated double quotes inside quotes produce literal quote matching
- Search bar tooltip on hover/focus shows the grammar rules.
- Search and assignee filters can be used together.
- Search works consistently in task, done, archived, and scheduled views via existing endpoints.
- Header filter button opens filter panel.
- Filter toggle in settings menu is removed/replaced for board page.
- Mobile always exposes search (including icon-expand variant).
- Healthy status widget is compact dot-only; unhealthy states expand.
- DB migration adds required indexes and is reversible.

---

## Risks and Mitigations

- Risk: Fulltext token/stopword behavior may surprise users.
  - Mitigation: Document behavior and add examples in UI help text.

- Risk: Checklist join inflates query cost on large boards.
  - Mitigation: Use EXISTS/subquery strategy + indexes; benchmark before merge.

- Risk: Header layout crowding on smaller desktop widths.
  - Mitigation: Explicit breakpoints, constrained input width, progressive collapse.

- Risk: Mixed source of truth between header and filter-panel search inputs.
  - Mitigation: Single BoardManager state + event-driven sync.

---

## Notes on Migration to PostgreSQL (Later)

No immediate migration is required for MVP. MySQL can deliver the requested baseline.

If/when quality targets exceed MySQL FULLTEXT capabilities:
- Introduce a search abstraction layer first.
- Add PostgreSQL-specific implementation second.
- Optionally keep dual support for a transition period.

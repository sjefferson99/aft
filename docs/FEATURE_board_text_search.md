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
- [ ] Confirm q parameter contract and empty-query behavior.
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
- [ ] Add Alembic migration for search indexes.
- [ ] Verify migration idempotency and rollback path.
- [ ] Validate query plans on representative data volume.
- [ ] Run migration + rollback test build in local/dev compose environment.
- [ ] Re-run affected API tests after migration application.

## Phase 3: Frontend search controls and sync
- [ ] Add header search control for board page (desktop + mobile).
- [ ] Add search control to board filter bar UI.
- [ ] Add 500ms debounce and board reload wiring in board.js.
- [ ] Keep search value synchronized between both controls.
- [ ] Add clear behavior and active-filter indicator integration.
- [ ] Add hover/focus tooltip describing AND/OR/quotes/escaped-quote behavior.
- [ ] Enforce minimum 2-character trigger (with #1 explicitly valid).
- [ ] Verify same search experience in task, done, and archived views.
- [ ] Run frontend build/smoke checks and board interaction tests for this phase.

## Phase 4: Filter button and settings menu changes
- [ ] Add filter-panel toggle button at end of search input.
- [ ] Remove/replace board filter toggle item from settings menu.
- [ ] Keep clear filters entry as-is or move if needed.
- [ ] Run UI regression checks for header menus and mobile drawer interactions.

## Phase 5: Status widget compact mode
- [ ] Healthy state renders dot-only with accessible tooltip.
- [ ] Error states auto-expand with full status text.
- [ ] Mobile behavior remains clean and non-overlapping.
- [ ] Run accessibility and responsive smoke checks for tooltip and expanded error modes.

## Phase 6: Consolidated validation and documentation
- [ ] Confirm each phase-level test/build gate completed and recorded.
- [ ] Add/finish API tests for:
  - [ ] q filtering (title/description/checklist)
  - [ ] spaces AND behavior
  - [ ] commas OR behavior
  - [ ] quoted phrase behavior
  - [ ] escaped quote behavior using repeated double quotes
  - [ ] unquoted #<digits> id-only matching
  - [ ] quoted "#<digits>" text-only matching
  - [ ] leading-zero and non-numeric hash tokens text-only matching
  - [ ] combined q + assignee filters
  - [ ] empty/no-result/min-length behavior
- [ ] Add UI test coverage for debounce + control sync behavior (if framework allows).
- [ ] Manual perf pass on realistic board size.
- [ ] Update user docs for board search behavior and limitations.
- [ ] Record post-MVP improvements from Future Search Enhancements section.

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

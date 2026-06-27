# Trello Import Feature Backlog

This document tracks two related sets of work:

1. **Trello-specific features** that have no current AFT equivalent and are dropped or warned on import — to be revisited when those AFT features land.
2. **Native AFT import/export gaps** — features that exist in AFT today but are not yet covered by the `aft-board` v1.0 export/import format. Each of these also has implications for the Trello importer.

When implementing any item in either section, update `TrelloBoardImportHandler` in `server/board_import_handlers.py` to take advantage of the new capability.

---

## Confirmed field mappings for initial implementation

These are straightforward mappings that the initial Trello importer should implement:

| Trello field | AFT field | Notes |
|---|---|---|
| `name` (board) | `board.name` | Direct |
| `desc` (board) | `board.description` | Direct |
| `closed` (board) | `board.archived` | Direct |
| `lists[].name` | `columns[].name` | Direct |
| `lists[].pos` | `columns[].order` | Re-index by sort position |
| `lists[].closed` | — | Modal option: skip or include archived lists |
| `cards[].name` | `cards[].title` | Direct |
| `cards[].desc` | `cards[].description` | Direct; label tags and URL attachments appended here too |
| `cards[].closed` | `cards[].archived` | Direct; modal option controls whether archived cards are included |
| `cards[].dueComplete` | `cards[].done` | Direct — `true` maps to done |
| `cards[].due` | `cards[].end_date` | Depends on native format gap (Part 2, item 1) being closed |
| `cards[].start` | `cards[].start_date` | Depends on native format gap (Part 2, item 1) being closed |
| `cards[].pos` | `cards[].order` | Re-index per list by sort position |
| `checklists[].checkItems[].name` | `checklists[].name` | Prefixed with group name: `"GroupName: Item"` when card has multiple checklists |
| `checklists[].checkItems[].state` | `checklists[].checked` | `"complete"` → `true` |
| `actions[]` where `type == "commentCard"` | `comments[].comment` | Via `action.data.text`; `action.date` → `created_at` |

---

## Part 1: Trello Import — Features to revisit when AFT equivalents are built

### Labels

**Trello**: Cards carry one or more coloured labels with optional text names. Defined at board level in `labels[]`, referenced per card via `idLabels[]`.  
**AFT status**: No label system exists.  
**Current importer behaviour**: Label names (or colour names where no text name is set) are prepended to the card description as `[LabelName]` tags. A pre-import warning is shown listing all cards that carry labels so users know their descriptions will be modified.  
**When AFT adds labels**: Remove the description-prefix fallback and map `labels[]` → AFT label records properly, associating them with cards via `idLabels`. Preserve both colour and name.

### File attachments

**Trello**: Cards support uploaded file attachments (`attachments[]` where `isUpload: true`). Note: URL "attachments" (links) are handled differently — see URL attachments below.  
**AFT status**: No file attachment system.  
**Current importer behaviour**: Dropped. A pre-import warning lists every affected card and the filenames that will be lost.  
**When AFT adds attachments**: Update the importer to handle `attachments[]` where `isUpload: true`.

### URL attachments

**Trello**: Cards can have URLs saved as attachments (`isUpload: false`), which appear as linked resources on the card.  
**AFT status**: No attachment concept; URLs live in card descriptions or comments.  
**Current importer behaviour**: URL attachments are appended to the card description (or card comment/journal entry if the URL was stored in the card's activity/comment context). A pre-import notice is shown.  
**When AFT adds link attachments**: Move URL attachments out of the description and into a dedicated attachment field instead.

### Card cover colour/image

**Trello**: Cards can display a coloured banner or image as a cover (`cover.color`, `cover.idAttachment`).  
**AFT status**: No card cover concept.  
**Current importer behaviour**: Silently dropped.  
**When AFT adds card covers**: Map `cover.color` → AFT cover colour.

### Voting

**Trello**: Members can vote on cards (`idMembersVoted`, `badges.votes`).  
**AFT status**: No voting system.  
**Current importer behaviour**: Silently dropped.

### Card location

**Trello**: Cards can carry a geographic location (`address`, `coordinates`, `locationName`).  
**AFT status**: No location concept.  
**Current importer behaviour**: Silently dropped.

---

## Part 2: Native AFT Import/Export — Existing features not yet in the format

These AFT features exist in the application today but are absent from the `aft-board` v1.0 export/import format. They should each be raised as a native import/export backlog item. The Trello importer depends on some of these being resolved (noted inline).

### 1. Card start_date and end_date

**AFT feature**: `Card.start_date` and `Card.end_date` columns, added in migration `033_add_start_end_date_to_cards.py`, used by the Planner.  
**Export gap**: Neither field appears in the `cards[]` export block (`board_routes.py` ~lines 1050–1066).  
**Import gap**: Neither field is parsed or written on import.  
**Trello implication**: The Trello importer maps `due` → `end_date` and `start` → `start_date`. These mappings will silently no-op until this native gap is closed. Close this native gap first, then the Trello importer will pick them up automatically.

### 2. Primary assignee — user mapping

**AFT feature**: `Card.assigned_to_id`. The field is exported but the importer explicitly sets it to `None`, pending a cross-instance user-mapping solution.  
**Current state**: Import meta returns `"assignee_mapping": "not_mapped"`. The count of ignored assignees is logged.  
**What's needed**: A user-mapping step — either a pre-import mapping table in the modal, or a post-import reassignment UI — to resolve exported user IDs to users in the target instance.  
**Trello implication**: Trello `idMembers` (card members) would map to the primary assignee once this is resolved. Currently dropped on Trello import for the same reason.

### 3. Secondary assignees — user mapping

**AFT feature**: `CardSecondaryAssignee` table. Exported but silently discarded on import (same user-mapping problem as above).  
**What's needed**: The same user-mapping solution as primary assignee; handle both in the same implementation pass.  
**Trello implication**: Same as above — Trello has no direct secondary assignee concept, but resolving this unblocks full assignee support in the native format.

### 4. Board public visibility

**AFT feature**: `Board.is_public` and `Board.public_slug`, added in migration `027_add_public_board_visibility.py`.  
**Export gap**: Neither field appears in the exported board object.  
**Import behaviour**: All imported boards are always created as private regardless of the source board's setting.  
**Decision needed when implementing**: Whether imported boards should ever carry over a public flag (probably not — private is the safer default, the user can publish after import).

### 5. Board roles and permissions

**AFT feature**: Board-scoped roles and permissions via `UserRole`/`Role` tables.  
**Export gap**: Not exported.  
**Import behaviour**: The imported board is owned by the importing user; no other role assignments are preserved.  
**Note**: This shares the cross-instance user identity problem with assignee mapping (items 2–3 above) and is likely lower priority until that is resolved.

---

## Trello import: silently dropped fields (no AFT equivalent planned)

These Trello fields are intentionally discarded with no planned mapping:

| Trello field | Reason for dropping |
|---|---|
| Board background, theme, `prefs` | Trello-specific UI preferences |
| List `color` | No column colour concept in AFT |
| Card template flag (`isTemplate`) | Imported as a regular card |
| Mirror card references (`mirrorSourceId`) | Imported as a regular card |
| Card and board email addresses | Trello-specific email-to-card inbox routing |
| Power-ups and plugin data | No AFT equivalent |
| Action history log | No import history concept in AFT |
| Member subscriptions | User-specific preference, not portable |
| Trello internal IDs (`nodeId`, `shortLink`, `shortUrl`) | Trello-specific identifiers |
| Organisation/workspace info (`idOrganization`) | Trello-specific |
| Checklist item due dates and member assignments | No AFT equivalent on checklist items |
| Board and card `limits` objects | Trello platform limits, not applicable |
| `badges` summary object on cards | Derived data, recalculated from imported content |

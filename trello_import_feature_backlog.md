# Trello Import Feature Backlog

This document tracks two related sets of work:

1. **Trello-specific features** that have no current AFT equivalent and are dropped or warned on import — to be revisited when those AFT features land.
2. **Native AFT import/export gaps** — features that exist in AFT today but are not yet covered by the `aft-board` export/import format (currently v1.1). Each of these also has implications for the Trello importer.

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
| `cards[].due` | `cards[].end_date` | Direct |
| `cards[].start` | `cards[].start_date` | Direct |
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

These AFT features exist in the application today but are not fully covered by the `aft-board` export/import format.

### Closed in format v1.1 (#494)

- **Card `start_date`/`end_date`** are exported and imported. Trello `due`/`start` and CSV dates already used the same import path.
- **Card `done_datetime`** is restored on import. Done cards with no source timestamp get the import time.
- **Board `is_public`** is exported for information only. Imports are always private and `public_slug` is never exported, because a carried-over slug could collide or publish a board without anyone choosing to. When the source board was public, `import_meta.warnings` says so. The import modal doesn't show post-import warnings yet.

### 1. Primary and secondary assignees — user mapping

**AFT feature**: `Card.assigned_to_id` and the `CardSecondaryAssignee` table. Both are exported as raw user IDs, and AFT imports ignore them on purpose, because IDs collide across instances.
**Current state**: Import meta returns `"assignee_mapping": "not_mapped"` with `ignored_primary_assignees_count` and `ignored_secondary_assignees_count`.
**What's needed**: Export a `users` block (source ID, username, display name) and reuse the Trello `member_map` flow in the import modal to map source users to local ones.
**Trello**: Already supported. `idMembers` map to primary and secondary assignees through `member_map`.

### 2. Board roles and permissions

**AFT feature**: Board-scoped roles via `UserRole`/`Role`.
**Export gap**: Not exported. The imported board is owned by the importing user, with no other role assignments.
**Note**: This has the same cross-instance user identity problem as item 1, so implement it with the same user mapping.

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

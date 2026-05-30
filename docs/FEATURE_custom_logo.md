# Feature: Custom Instance Logo

**Branch:** `feature/custom-logo`  
**Status:** In progress

## Overview

Add the ability for administrators to upload a custom instance-wide logo. Uploaded logos are stored in a `logos/` subdirectory of the existing `backgrounds_volume` Docker volume (no new volume or nginx changes required). The active logo filename is tracked in a new `InstanceConfig` DB table. `header.js` fetches the active logo on every page load and dynamically overrides the header image and favicon. Management UI lives in the Settings page, visible only to users with the new `branding.edit` permission.

Implementation approach is intentionally two-stage:
1. **MVP path (fast):** one uploaded file only, rendered everywhere.
2. **Final optimization path:** auto-generate format variants and let render code use the most appropriate format.

### Logo file constraints (MVP)
- **Maximum file size**: 100 KB (enforced server-side; logo is loaded on every page)
- **Accepted formats**: `.webp`, `.png`, `.jpg`, `.jpeg`, `.gif`
- **Recommended upload**: WebP or PNG for best quality-to-size ratio
- **Single stored source file** per upload (`logo_<timestamp>_<uuid>.ext`) — immutable caching safe; old files not auto-deleted in this MVP

---

## Completion Checklist

- [ ] CONTRIBUTING.md pre-submission checklist complete
- [ ] All tests pass (`pytest -v` from fresh DB)
- [ ] Swagger docstrings on all new routes
- [ ] `expected_tables` updated in `server/security_validators.py`
- [ ] Schema validation tested with backup/restore
- [ ] Accessibility: ARIA attributes, keyboard nav, screen reader labels
- [ ] Security: file size limit, extension validation, path traversal protection
- [ ] AGENT_CONTEXT.md updated if workflow changed

---

## Tasks

### Phase 1: Permission + Model
- [x] **1.1** Add `branding.edit` to `PERMISSION_DEFINITIONS` in `server/permissions.py`
- [x] **1.2** Add `branding.edit` to `administrator` role's `INITIAL_ROLES` permissions list in `server/permissions.py`
- [x] **1.3** Add `InstanceConfig` model to `server/models.py` — columns: `id` (PK), `key` (String(255), unique, not null), `value` (String(1024), nullable)
- [x] **1.4** Create migration `028_add_instance_config_table.py` in `server/alembic/versions/` using method 2 (manual) from `MIGRATION_GUIDE.md`
- [x] **1.5** Add `instance_config` to `expected_tables` list in `server/security_validators.py`'s `validate_schema_integrity()` function
- [x] **1.6** Add `InstanceConfig` import to `server/alembic/env.py`

### Phase 2: Backend API (`server/branding_routes.py`) + API tests
New blueprint `branding_bp`, registered in `server/app.py`. Use `theme_routes.py` as implementation template for file handling, path traversal guards, `require_permission`, `create_error_response`, and `create_success_response` patterns.

- [x] **2.1** `GET /api/branding/logo` — **no auth required**; queries `InstanceConfig` for key `custom_logo_filename`; returns `{"filename": "<name>"}` or `{"filename": null}`. Swagger tag: `Branding`.
- [x] **2.2** `POST /api/branding/logo` — requires `branding.edit`; validates extension (`.webp`, `.png`, `.jpg`, `.jpeg`, `.gif`); enforces **100 KB** max file size (checked in Python via `file.seek(0, 2)` / `file.tell()`); saves to `/var/www/images/backgrounds/logos/logo_<timestamp>_<uuid>.ext`; upserts `InstanceConfig(key='custom_logo_filename', value=filename)`; returns `{"filename": "<name>"}`. Swagger tag: `Branding`.
- [x] **2.3** `DELETE /api/branding/logo` — requires `branding.edit`; deletes the `InstanceConfig` row (does NOT delete file from disk); returns success response. Swagger tag: `Branding`.
- [x] **2.4** Register `branding_bp` in `server/app.py`
- [x] **2.5** Add API-only endpoint coverage in `server/tests/test_api_branding.py`
  - Public `GET /api/branding/logo` returns `filename: null` by default
  - Authenticated `GET /api/branding/logo` returns `filename: null` by default
  - Successful upload returns filename and persists through subsequent GET
  - Oversize upload is rejected at 100 KB
  - Invalid extension is rejected
  - Non-admin upload is denied
  - Successful reset returns to `filename: null`
  - Non-admin reset is denied
  - Public GET still works after upload

### Phase 3: Frontend — Dynamic Logo in `header.js` (MVP)
After the header HTML is injected into the DOM (the existing block around line 266 that sets `logoImg.src = LOGO_PATH`), fetch `GET /api/branding/logo` with AbortController/5-second timeout (per `FRONTEND_ERROR_HANDLING.md`). If a custom filename is returned, override both `.header-logo` `src` and all `link[rel="icon"]` `href` values to `/images/backgrounds/logos/<filename>`. Fall back silently to `LOGO_PATH`/`FAVICON_PATH` constants on null response, network error, or timeout.

- [x] **3.1** Add `applyCustomLogoIfSet()` async method to the header class in `www/js/header.js`
- [x] **3.2** Call `applyCustomLogoIfSet()` from within the header load flow, after the default logo constants have been applied

### Phase 4: Frontend — Settings UI
Split `settings.html` into two panels: user-specific settings and instance-global settings.

- [x] **4.1** Keep existing controls in a **User Settings** panel (`www/settings.html`) for user-scoped settings only
- [x] **4.2** Add a new **Instance Global Settings** panel (`www/settings.html`) containing branding controls:
  - Current logo preview `<img id="current-logo-preview">` with alt text
  - File input (`accept=".webp,.png,.jpg,.jpeg,.gif"`) + "Upload Logo" button
  - Help text: recommended WebP or PNG, max 100 KB
  - "Reset to Default" button
  - Status message element
  - Full ARIA attributes per `ACCESSIBILITY.md`
- [x] **4.3** Use the same permission visibility approach as other pages in `www/js/settings.js`:
  - Wait for `window.userDataReady`
  - Use `hasPermission('branding.edit')` to determine visibility of the global panel
  - Hide the global panel entirely for users without relevant permissions
- [x] **4.4** Add branding section behavior in `www/js/settings.js`:
  - On page load: call `GET /api/branding/logo` and populate preview when panel is visible
  - Upload handler: validate file size client-side (100 KB) before POST to `/api/branding/logo`, show status/toast on success/error, refresh preview
  - Reset handler: DELETE `/api/branding/logo`, revert preview to default AFT logo path
  - All fetch calls use AbortController with 5-second timeout per project standard
- [x] **4.5** Rename the menu entry text from **User Settings** to **Settings** in both desktop and mobile header menus (`www/components/header.html`)

### Phase 5: Final Optimization — Auto-generated format variants
Add this phase after MVP is merged and stable.

- [ ] **5.1** Add Pillow dependency in backend requirements and Docker image
- [ ] **5.2** On upload, generate normalized logo variants from source file:
  - `logo_<id>.webp` (primary for modern browsers)
  - `logo_<id>.png` (fallback for broad compatibility, including favicon)
- [ ] **5.3** Persist a small metadata JSON in `InstanceConfig` instead of a single filename, for example:
  - `{\"source\": \"logo_...ext\", \"webp\": \"logo_...webp\", \"png\": \"logo_...png\"}`
- [ ] **5.4** Extend `GET /api/branding/logo` response to include variant URLs while staying backward-compatible with MVP payload
- [ ] **5.5** Update `header.js` rendering logic:
  - Header logo uses WebP variant when available
  - Favicon links include PNG fallback and WebP where appropriate
  - Keep graceful fallback to single-file MVP response
- [ ] **5.6** Add API tests for conversion success/failure paths and response compatibility

---

## Files to Create
| File | Purpose |
|------|---------|
| `server/branding_routes.py` | New blueprint with 3 logo endpoints |
| `server/alembic/versions/028_add_instance_config_table.py` | DB migration |
| `server/tests/test_api_branding.py` | API tests |

## Files to Modify
| File | Change |
|------|--------|
| `server/permissions.py` | Add `branding.edit` permission + to `administrator` role |
| `server/models.py` | Add `InstanceConfig` model |
| `server/alembic/env.py` | Import `InstanceConfig` |
| `server/app.py` | Register `branding_bp`; add `instance_config` to `expected_tables` |
| `www/js/header.js` | Add `applyCustomLogoIfSet()`, call after header load |
| `www/components/header.html` | Rename "User Settings" menu labels to "Settings" (desktop + mobile) |
| `www/settings.html` | Split page into User Settings and Instance Global Settings panels; add branding controls |
| `www/js/settings.js` | Add permission-gated global panel visibility and branding load/upload/reset logic |
| `www/css/settings.css` | Add panel and branding layout styles for the updated settings page |

## No Changes Required
- `compose.yml` — logos stored in existing `backgrounds_volume` subdirectory
- `server/nginx.conf` — existing `^~ /images/backgrounds/` location already serves subdirectories with 30-day immutable caching
- Any HTML favicon `<link>` tags — `header.js` already overrides the first `link[rel="icon"]` dynamically

---

## Notes

### Why `InstanceConfig` table?
A generic key-value table is preferable to a dedicated `custom_logo_filename` column because:
- It avoids schema migrations for each future instance-level setting
- Keeps the logo MVP self-contained while leaving room for future branding settings (e.g. instance name, accent colour)

### Nginx caching and logo changes
Logos are served at `/images/backgrounds/logos/<unique-filename>` and will be cached immutably for 30 days by the browser (same rule as theme backgrounds). Because each upload generates a new unique filename, a logo change will immediately load the new file — no cache busting needed.

For Phase 6 variant generation, the same immutable caching behavior applies because generated WebP/PNG assets will also use unique filenames.

### File size enforcement
- **Server-side**: `file.seek(0, 2); size = file.tell(); file.seek(0)` — checked before saving. Returns 400 if > 100 KB.
- **Client-side**: `file.size > 102400` pre-check before POST to avoid wasted upload. Returns user-friendly toast message.
- Nginx `client_max_body_size` is currently 128 MB; the 100 KB Python check is the binding constraint.

### PNG vs WebP favicon strategy
MVP uses a single uploaded file and applies it to both header and favicon targets for speed of delivery.

Phase 6 introduces automatic variant generation so rendering can prefer WebP where suitable while maintaining PNG fallback for maximum compatibility.

For existing default assets, keeping both `AFT_logo.webp` and `AFT_logo.png` remains intentional and harmless.

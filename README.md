# AFT
## What is it?
Aim, Focus, Track - AFT is an Application For Tasks, it provides an Adaptive Flow Toolkit to let you organise your tasks in the way that makes sense for you and then get them done.

It is fully open source and is self hosted using a simple docker deployment approach.

> Looking for the latest features and changes? Check the GitHub Releases page: https://github.com/sjefferson99/aft/releases

### Kanban working style
You can use it as a simple set of Kanban boards, making one or more boards with custom columns including a done column, allowing you to drag cards between them as necessary to reflect your work. 

### Agile working style
You can create boards for each epic or group of tasks that need to be done and then create columns within the boards to represent features or sets of common tasks that can be ticked off when done showing the completion of that column or feature.

### Scheduling
I wrote AFT because I couldn't find self hosted Kanban software that allowed you to specify a schedule for certain tasks to appear in your to do list, keeping track of things like regular maintenance, bin day, monthly accounts etc.

### Intuitive UI
AFT should be easy to use without reading manuals and all core features should be straightforward to discover and use by simply loading it up and making a start - if it isn't in any way, log an issue in the [GitHub repo](https://github.com/sjefferson99/aft) and we'll fix it up.
There is comprehensive documentation in the form of this readme, the Swagger API page and the in app docs page for more advanced and time saving tricks, but these are not needed to use everything in AFT as a standard user.

### API
The entire application is based on a server container that exposes all functionality via API. The UI is a separate container with a javascript web app that adds a layer over the API. You can easily interact with any element of AFT programmatically over API, or even completely rewrite the UI or drop into a larger application.
Check the API Docs page in the user menu for more details.

### Security
Authentication should be rock solid, data should be secure, known exploits patched regularly and best practice design followed for preventing injection attacks, cross site scripting etc. Details of security review performed and mitigated are in the docs folders.

## Deployment

### Quick start (recommended)
No repo clone needed — images are published to GitHub Container Registry on each release.

```sh
curl -O https://raw.githubusercontent.com/sjefferson99/aft/main/compose.example.yml
curl -O https://raw.githubusercontent.com/sjefferson99/aft/main/.env.example
mv .env.example .env
mv compose.example.yml compose.yml
```

> **Note:** The GHCR images are public, so `docker compose pull` requires no authentication. If you are pulling a private fork, log in first with `docker login ghcr.io`.

- Edit `.env` with your passwords, CORS config, and any other options (see comments in the file and the configuration details below)
- Keep your deployed `compose.yml` aligned with the latest `compose.example.yml` when upgrading. Older/custom compose files can miss required env wiring (for example nginx `env_file`) and silently break embed policy config.
- `docker compose pull`
- `docker compose up -d`
- Adjust backup folder permissions as below
- Navigate to `http(s)://<docker-host>`

To pull the latest release in future: `docker compose pull && docker compose up -d`

When updating an existing deployment, refresh your compose template first and merge any new service/env settings:

```sh
curl -o compose.example.yml https://raw.githubusercontent.com/sjefferson99/aft/main/compose.example.yml
diff -u compose.yml compose.example.yml
```

After merge/apply, recreate services so env changes take effect:

```sh
docker compose up -d --force-recreate
```

Available images:
- `ghcr.io/sjefferson99/aft:latest` — API server only
- `ghcr.io/sjefferson99/aft-web:latest` — nginx + UI (proxies to the server)

> **Raspberry Pi / arm64:** Both images are published as multi-architecture manifests covering `linux/amd64` and `linux/arm64`. The same `compose.example.yml` works unmodified on a Raspberry Pi or other arm64 host — `docker compose pull` automatically selects the matching architecture, no extra configuration needed.

### Server-only deployment
Remove or comment out the `nginx` service in `compose.example.yml` before renaming it to `compose.yml` to run the API server without the web UI.

### Development / build from source
Use `compose.yml` to build images locally from the repo:

- Always use `compose.yml` for local development/testing.
- Always include `--build` when starting the dev stack so current source changes are applied.
- Use `compose.example.yml` as the GHCR deployment template.

```sh
git clone https://github.com/sjefferson99/aft.git
cd aft
docker compose up --build -d
```

## Features in detail
### Working Style Configuration
The application supports different working styles to accommodate various team preferences.

- The Working Style option in General Settings sets the default for new boards you create.
- Existing boards keep their own working style and can be changed from each board's menu.

![Working Style Options](images/working_style_options.png)

**Available Options:**
- **Kanban** - Traditional column-based workflow where cards move through stages (To Do, In Progress, Done, etc.)
- **Agile** - Enables done tracking and a dedicated Done View on the board

In Agile mode, cards use Done/Not Done status, and you can also archive a card to take it off the board without marking it done, for example work you decided not to do. Archive workflows and the Archived View are available in both modes. For detailed information on using these features, see the Docs page (accessible from the user menu in the header).

### 📋 Board Management
- **Create Multiple Boards** - Organise different projects with separate Kanban boards
- **Update Board Details** - Rename boards and modify their properties
- **Delete Boards** - Remove boards when projects are complete
- **Archive Boards** - Archive boards from the boards list to declutter active workspaces while preserving data
- **Unarchive Boards** - Restore archived boards from the Archived Boards view
- **Boards View Switching** - Toggle between Active Boards and Archived Boards from the header view menu
- **Default Board Setting** - Set a default board to load on startup
- **Board Statistics** - View counts of boards, columns, and cards
- **Import Boards** - Import boards from AFT JSON exports, Trello JSON exports, or CSV files via the Import Board button on the boards list

### 📥 Board Import
- **AFT JSON** - Re-import any board exported from AFT, including columns, cards, card start/end dates, checklists, comments and scheduled cards. Assignees are not carried over, because user IDs differ between instances. Imported boards are always private, even if the source board was public
- **Trello JSON** - Import Trello board exports; labels are prepended to descriptions, URL attachments are appended, checklists and dates are mapped, member mapping is supported
- **CSV Import** - Import cards from a spreadsheet-style CSV with columns: `title`, `column`, `assignee`, `description`, `checklist_items` (pipe-separated; append `[done]` to mark checked), `start_date`, `end_date` (YYYY-MM-DD)
  - **Download Template** - A template CSV is available from the import modal hint text before selecting a file
  - **New Board** - Create a new board from the CSV (name defaults to the filename stem)
  - **Existing Board** - Import into an existing board with a choice of conflict strategy:
    - **Duplicate** - All CSV cards are added as new; cards matching an existing column + title receive a numeric suffix (e.g. `Card (2)`)
    - **Overwrite** - Cards matching an existing column + title are replaced in place; new cards are added
  - **Preview** - The import modal shows which cards will be affected before you confirm
  - **Unknown assignees** - Cards with unrecognised usernames are imported without an assignee; a warning is shown

### 🌐 Public Board Sharing (Read-Only)
- **Public Visibility Toggle** - Board owners/editors can switch a board between private and public from the board menu.
- **Stable Share Link** - Making a board private and public again keeps the same public slug unless you explicitly rotate it.
- **Copy Public Link** - Signed-in users see a small "P" badge in the header on public boards. Click it, or use "Copy Public Link" in the board menu, to copy the link.
- **Rotate Public Link** - Use "Rotate Public Link" in the board menu to immediately invalidate the old URL and issue a new one.
- **Dedicated Public Page** - Public links open at `/public-board.html?slug=<slug>` for anonymous viewing.
- **Instance Theme Alignment** - Public board viewers use the configured instance default theme, not a fixed hardcoded theme.
- **Read-Only by Design** - Public boards do not expose edit controls, websocket mutation paths, assignee metadata, or commenter identity fields.
- **Anonymous Write Denial** - Anonymous POST/PATCH/DELETE requests to protected board/card endpoints remain denied.
- **Traffic Hardening** - Public board reads are throttled at both application and reverse-proxy layers.

![Board List](images/boards.png)

### 📊 Column Management
- **Flexible Columns** - Create custom columns for your workflow (e.g., To Do, In Progress, Done)
- **Reorder Columns** - Rearrange columns to match your process
- **Column Operations** - Add, edit, or delete columns as your workflow evolves
- **Column Menu** - Access column actions via three-dots menu:
  - **Move All Cards** - Batch move all cards from one column to another (top or bottom position)
  - **Archive All Cards** - Archive all active cards in a column at once
  - **Archive After...** - Automatically archive cards older than a specified time period
    - Configure time period (e.g., 7 days, 2 weeks, 3 months)
    - Preview which cards will be archived before committing
    - See the most recent card that will be archived with card details
    - Uses card's last update time to determine eligibility
    - Ideal for automatically cleaning up completed or stale tasks
  - **Unarchive All Cards** - Unarchive all archived cards in a column (visible in archive view)
  - **Delete All Cards** - Remove all cards from a column
  - **Delete Column** - Remove the entire column

![Kanban Board](images/board.png)

### 🎴 Card Management
- **Create Cards** - Add task cards with titles and descriptions
- **Move Cards** - Drag cards between columns to track progress
- **Create Cards** - New cards can start with dates, a duration, assignees, a checklist and a schedule, using the same keyboard rules as editing
- **Move to Top** - Send a card to the top of its column from the edit card modal, with the T shortcut, or from the card itself by choosing Move to top in your Card Actions setting. It always goes to the top of the whole column, even when a search, filter or view hides other cards, so you can filter to find a card, move it up, and see it first when you clear the filter
- **Update Cards** - Edit card details, titles, descriptions, and comments. Edited comments are marked as edited. Changes save as you leave each field, with a small "Saved" indicator. Enter saves and closes the card, Shift+Enter adds a new line, and Escape reverts the field you're editing, then closes. On touchscreens Enter adds a new line in descriptions and comments
- **Assign Responsibility** - Set a primary assignee and optional secondary assignees per card from users with board access
- **Assignee Avatars** - Cards show the primary assignee initials in a bottom-left avatar circle using the assignee's profile colour
- **Board Assignee Filters** - Open/toggle the compact assignee filter bar from the header search field's filter icon to show cards for selected assignees, include unassigned cards, and optionally match secondary assignees. When filters are active, a visual indicator appears next to the board name. Clear all filters quickly via the board menu "Clear Filters" option.
- **Board Text Search** - Search cards from the header or filter bar with shared state and a 500ms debounce. Search matches card title, description, and checklist item text. Query grammar supports spaces as AND, commas as OR, quoted exact phrases, and repeated double quotes inside phrases for literal quote matching. API search contract limits are: max 200 characters, max 12 comma-separated OR groups, max 24 total terms, and max 80 characters per term; requests outside this contract return HTTP 400.
- **Card ID Search Tokens** - Use unquoted `#123` to match card ID 123 only. Use quoted `"#123"` for text-only matching. Tokens like `#00379`, `#abc`, and `##123` are treated as normal text tokens.
- **Delete Cards** - Remove completed or cancelled tasks
- **Archive Cards** - Archive completed cards to declutter your board while preserving history
- **Unarchive Cards** - Restore archived cards back to active view when needed
- **View Switching** - Switch between Task, Scheduled, Archived, and Planner views using the header dropdown
- **Batch Operations** - Archive or unarchive multiple cards at once via column menu
- **Timestamps** - Track creation and last update times for all cards, columns, boards, and checklist items
  - Cards display "Updated X ago" on the board view
  - Edit modal shows created and updated timestamps for cards
  - Cards also track a nullable done timestamp (`done_datetime`) for completion reporting
  - In **Agile** mode, using the Done button sets `done_datetime` when a card is marked done
  - Moving cards into done-like columns sets `done_datetime` (case-insensitive): `done`, `complete`, `completed`, `finished`, `resolved`, `closed`, `shipped`
  - Checklist items show created/updated timestamps in tooltips
  - Timestamps update when content changes (title, description, column) but not when reordering
  - Adding/editing comments or checklist items updates the parent card's timestamp

![Card Detail](images/card_detail.png)
![Archive View](images/archive_screen.png)

### ✅ Checklist Items
- **Task Breakdown** - Add checklist items to cards for subtasks
- **Track Progress** - Check off items as you complete them
- **Update Checklists** - Modify checklist item text and completion status
- **Remove Items** - Delete checklist items when no longer needed

### 💬 Comments
- **Card Discussion** - Add comments to cards for collaboration
- **Comment History** - View all comments on a card with timestamps
- **Delete Comments** - Remove outdated or incorrect comments

### 🔄 Scheduled Cards (Recurring Tasks)
- **Template Cards** - Convert any card into a recurring task template
- **Flexible Scheduling** - Create cards automatically on a schedule:
  - **Frequency Options**: Every N minutes, hours, days, weeks, months, or years
  - **Start Date/Time**: Configure when the schedule begins
  - **End Date/Time**: Optional schedule expiration (auto-disables when reached)
- **Schedule Management**:
  - **Enable/Disable**: Turn schedules on or off without deleting them
  - **Edit Schedules**: Update frequency, dates, or settings at any time
  - **Delete Schedules**: Remove recurring schedules when no longer needed
- **Duplicate Control** - Prevent duplicate cards in the same column or allow multiple instances
- **Live Preview** - See the next 4 scheduled run times before saving
- **Create Card Now** - Create a one-off card from an existing schedule without changing its run times
- **Scheduled View** - Dedicated view for managing template cards (separate from task view)
- **Automatic Creation** - Cards created every minute based on enabled schedules
- **Schedule Tracking** - Auto-generated comments track which schedule created each card
- **Checklist Preservation** - Template checklist items are copied to new cards
- **Manual Generate Tasks (Admin)** - From System Info, admins can open a Generate Tasks modal, choose a start/end date-time range, preview exactly which cards would be created, then run generation on demand for that range

![Scheduled Cards](images/scheduled_cards.png)
![Schedule Modal](images/schedule_modal.png)

### 📅 Planner View
- **Year Overview** - See a full calendar year as 12 mini month grids, with coloured dots indicating days that are free, busy (have real cards), or scheduled (have projected recurring-schedule occurrences)
- **Month Detail** - Drill into any month to see a full calendar grid with cards displayed as chips on the days they span; click a month block in the year view to open it, or use the Back button to return
- **Year/Month Navigation** - Previous/next arrows navigate between years or months
- **Card Interaction** - Click a card chip to edit it or enter placement mode to move it to a new start date by clicking any day in the year view
- **Add Card** - Click an empty day cell in month view to create a new card pre-dated to that day
- **Overflow Expand/Collapse** - Days with more than three cards show a "+N more" button; click to expand all cards for that day inline
- **Show Scheduled Toggle** - Overlay projected future occurrences of recurring schedules (shown in a distinct colour) across both year and month views
- **Show Columns Toggle** (month view only) - Display the board column name on each card chip
- **Show Times Toggle** (month view only) - Display card start/end times on each card chip

### ⚙️ Settings & Configuration
- **Customisable Settings** - Configure application preferences including default board
- **Time Format Settings** - Choose between 12-hour (AM/PM) or 24-hour time display
- **Touchscreen Mode** - A per-user setting for large touchscreens and kiosks: scroll boards with a finger, press and hold a card to drag it, and use larger buttons, with menus that open by tap
- **Instance Default Theme (Global)** - In Instance Global Settings, users with `branding.edit` can choose a default theme for:
  - New users at account creation time
  - Anonymous public board viewers
  - Existing users are not changed automatically
  - Only system themes and promoted global themes appear in the default-theme selector
  - If unset or invalid, fallback remains the built-in Fresh Green system theme
- **Global Theme Promotion** - Users with `branding.edit` can promote a user-created theme to global visibility so all users can select and copy it
- **Global Theme Demotion** - Global themes can be demoted back to user scope from Instance Global Settings when they are no longer being shared
- **Working Style Default (New Boards)** - Set your default board style for boards created in the future
  - **Kanban**: Traditional column-based workflow where cards move through stages
  - **Agile**: Board-level done tracking with Done/Not Done workflow
  - **Board-Level Override**: Existing board style is managed from that board's menu
  - **Done Button**: Mark cards as complete without moving them between columns in Agile mode
  - **Done View**: Dedicated view to see completed cards in Agile mode
  - **Archived View**: Available in both modes; in Agile mode it lists done and not-done archived cards together
  - **Smart Column Counts**: See total and done counts in column headers (e.g., "To Do (2/5)")

![Settings](images/settings.png)

### 🎨 Theme Builder
- **Visual Customisation** - Create and customise colour themes for the entire application
- **Database-Backed Themes** - Themes stored in database, persist across sessions
- **System Themes** - Pre-built themes (Default, Dark, Light, Solarized) that cannot be modified
- **Custom Themes** - Create unlimited custom themes with your preferred colours
- **Global Themes** - Promote selected user themes to make them available instance-wide alongside system themes
- **Theme Management**:
  - **Create**: Copy existing themes to create your own variants
  - **Edit**: Modify all colour variables (primary, secondary, status, text, backgrounds, header) on user-scoped themes
  - **Rename**: Update theme names for better organisation on user-scoped themes
  - **Import/Export**: Share themes as JSON files
  - **Apply**: Instantly preview and apply themes to your session
- **Background Images** - Select from included background images or upload custom images
  - Pre-loaded with 4 default backgrounds (At the Beach, Sunrise, Welcome to the Jungle, etc.)
  - Upload custom background images for unique theme styling
  - Background images stored in Docker named volume (persistent across restarts)
- **Background Images** - Select from available background images or upload custom images
- **Live Preview** - See colour changes in real-time as you edit
- **Organised Theme List** - Themes grouped by User Themes, Global Themes, and System Themes, alphabetically sorted
- **Read-Only Shared Themes** - System themes and promoted global themes are protected from direct modification
- **Unsaved Changes Protection** - Warning modal when applying themes with unsaved changes
- **Comprehensive Colour Control** - Configure 15+ colour variables:
  - Primary and secondary colours with hover states
  - Status colours (success, error, warning)
  - Text colours (primary, muted, inverted)
  - Background colours (light, dark, card backgrounds)
  - Header colours (background, text, menu, buttons, icons)
- **Accessibility** - Full ARIA support, keyboard navigation, screen reader compatible

![Theme Builder](images/theme_builder.png)

### Automatic Database Backups - Schedule recurring backups to protect your data ###
- Configurable frequency (minutes, hours, or days)
- Flexible start time alignment for backup scheduling
- Automatic retention management (keep 1-100 most recent backups)
- Backup health monitoring with status indicators
- Overdue backup detection
- Backups saved to host filesystem via bind mount (`./backups/`)
- Restores show a spinner with the current step, and while data is loading, the table being restored and how much of the backup has been sent to the database

![Backup Settings](images/backup_configuration.png)

### � Documentation
- **Comprehensive Docs** - Full documentation available in-app via the Docs page
- **Keyboard Shortcuts** - Quick reference for board shortcuts (N for a card at the top, M for a card at the bottom, C for a column nearest the mouse, T to move the card under the mouse to the top)
- **Adding Columns** - The ways to add a column, including between existing columns
- **Working Style Guide** - Detailed guide on using different working styles:
  - Available working style options and when to use each
  - Done/Not Done button functionality and task completion tracking
  - Done View feature for reviewing completed work
  - Column count display and what each number means
  - Screenshots and visual examples of each feature
- **Easy Access** - Link to Docs from the user menu in the header

### 🔔 Notifications
- **System Notifications** - Receive alerts about important events
- **Backup Notifications** - Alerts for overdue backups or backup failures
- **Schedule Notifications** - Alerts for schedule errors or when schedules end
- **Version Notifications** - Automatic alerts when new AFT releases are available
- **Documentation Notification** - Welcome notification on first installation directing users to Docs
- **Action Buttons** - Optional action buttons on notifications with secure URL validation
- **Notification Centre** - View and manage all notifications from the header
- **Mark as Read** - Individual or bulk mark notifications as read and delete
- **Notification Badge** - Unread count indicator in header

![Notifications](images/notifications.png)

### 🔧 System Info
- **Version Tracking** - Monitor application and database schema versions
- **DB Stats** - Statistics on task entities in the database
- **Service Monitoring** - Status of running system services and enable/disable toggle
- **Generate Scheduled Tasks (Admin)** - Manually generate scheduled cards for a selected date-time range with a preview before execution

![System Info](images/system_info.png)

### 🤖 Background Services
- **Backup Scheduler** - Automatic database backup service running every minute
  - Monitors backup schedule and creates backups at configured intervals
  - Enforces retention policies automatically
  - Checks disk space before creating backups
  - Creates notifications for failures or overdue backups
- **Card Scheduler** - Automatic card creation service running every minute
  - Processes enabled schedules and creates cards at scheduled times
  - Enforces duplicate prevention rules
  - Auto-disables schedules past their end date
  - Creates notifications on errors
  - Adds tracking comments to created cards
- **Housekeeping Scheduler** - Automatic maintenance service running every hour
  - Checks GitHub for new AFT releases
  - Creates notifications when updates are available
  - Prevents duplicate notifications for the same version while one still exists, read or unread
  - Can be enabled/disabled via System Info page

### 🔌 API Documentation
- **Interactive API Docs** - Built-in Swagger UI at `/api/docs`
- **RESTful API** - Full API access for integrations and automation
- **Health Checks** - Database connectivity and version endpoints
- **Card Completion Timestamp** - Card payloads now include `done_datetime` (ISO datetime or null)

Public board API endpoints include:
- `GET /api/public/boards/<slug>` - Anonymous read-only board payload
- `POST /api/boards/<id>/public-link/rotate` - Authenticated link rotation for public boards

Default theme API endpoints include:
- `GET /api/settings/default-theme` - Authenticated endpoint to read the current instance default theme
- `PUT /api/settings/default-theme` - Requires `branding.edit` to update the instance default theme

![API Documentation](images/api_docs.png)

## 📡 System Status Widget

The header displays a real-time system status indicator in the top-right corner. This widget monitors three critical system components and displays their health status:

### Status Indicator Colours & Meanings

| Status | Icon | Color | Meaning | Troubleshooting |
|--------|------|-------|---------|-----------------|
| **Connected** | ✅ | Green | All systems operational | None needed - everything is working normally |
| **Server Disconnected** | ❌ | Red | Cannot reach API server (blocks all operations) | Server is down, check docker containers with `docker compose ps`. Verify network connectivity. Try refreshing the page. |
| **WebSocket Disconnected** | ❌ | Red | Real-time updates unavailable (REST API still works) | Refresh page to reconnect. If persistent, check browser console for errors. Verify CORS settings in `.env`. **Note:** Database operations (create/edit/delete) still work via REST API. |
| **DB Error** | ❌ | Red | Database connection failed (blocks all operations) | Check database container health: `docker compose logs db`. Verify database is running and accessible. Check disk space. |

### Status Checking Order (Priority)

The widget checks system status in this order and stops at the first failure:

1. **Server Connectivity** (Highest Priority)
   - Makes HTTP request to `/api/test`
   - If server doesn't respond or returns error, shows "Server Disconnected"
   - Other checks are skipped when server is down

2. **WebSocket Connection** (Medium Priority)
   - Only checked on board/dashboard pages (where real-time updates are needed)
   - Monitors Socket.IO connection status
   - If loading takes >30 seconds, shows "WebSocket Disconnected"
   - **Important:** WebSocket failures do NOT block database operations
   - REST API calls (create, edit, delete) continue to work normally
   - Only real-time sync features are affected (live updates from other users)

3. **Database Health** (Lower Priority)
   - Queries database directly via API
   - If server is OK but database fails, shows "DB Error"
   - Indicates database-specific issues

## Configuration

### CORS Origins (HTTP/HTTPS/WebSocket)
The application enforces CORS (Cross-Origin Resource Sharing) on all web traffic: HTTP, HTTPS, and WebSocket connections. By default, CORS is restricted to localhost addresses for development safety. For production deployments or when accessing from different hosts, update the `CORS_ALLOWED_ORIGINS` environment variable in `.env`:

**Development (default):**
```
CORS_ALLOWED_ORIGINS=http://localhost,http://127.0.0.1,https://localhost,https://127.0.0.1
```

**Production (example with multiple trusted domains):**
```
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

**Custom Host / Docker Host Access:**
```
CORS_ALLOWED_ORIGINS=http://your-docker-host-ip,https://your-docker-host-ip,https://your-hostname
```

Provide a comma-separated list of all origins that should be allowed to connect, including the exact scheme and host you use in the browser (for example https://staustell). This prevents Cross-Site Request Forgery and Cross-Site WebSocket Hijacking attacks by only accepting connections from trusted sources.

### Public Board iframe Embedding (Trusted Sites)
If you plan to embed public boards on external websites, keep framing restricted to trusted partner origins only.

Set `EMBED_ALLOWED_ORIGINS` in `.env` as a comma-separated list of origins.
Both exact origins and controlled subdomain wildcard patterns are supported:

```
EMBED_ALLOWED_ORIGINS=https://partner-a.example,https://portal.partner-b.example
```

Example for an owned domain and all its subdomains:

```
EMBED_ALLOWED_ORIGINS=https://partner.example,https://*.partner.example
```

Notes:

- This setting is for frame-embedding allowlists (clickjacking protection), not API CORS.
- Keep the list minimal. If you use wildcard patterns, scope them to domains you control.
- Wildcard patterns (for example `https://*.partner.example`) do not include the apex domain; include both when required.
- The nginx service must load `.env` and pass `EMBED_ALLOWED_ORIGINS` into the container runtime. Both `compose.example.yml` and `compose.yml` include this by default; preserve it if you customize compose.
- After changing `.env`, recreate nginx so startup scripts regenerate CSP headers: `docker compose up -d --force-recreate nginx`.
- Public board iframe use and parent-site direct API calls are different:
  - iframe usage: board interactions run inside the AFT origin and should not require parent-origin CORS.
  - parent-site direct API calls: still require that parent origin in `CORS_ALLOWED_ORIGINS`.

#### iframe Embed Troubleshooting
- "Refused to frame" in browser console:
  - Ensure the host origin is listed in `EMBED_ALLOWED_ORIGINS`.
  - Recreate/restart nginx so the runtime header include is regenerated.
- Board opens directly but not in partner site:
  - Confirm partner page uses the same exact scheme/host/port you allowlisted.
  - Confirm partner page is not forcing an overly restrictive iframe `sandbox`.
- Works on published page but fails in WordPress editor/preview:
  - The wp-admin/editor chain may introduce sandboxed or intermediate frame ancestors that do not match your allowlist.
  - Validate on the real published page URL (not `wp-admin` preview) before concluding embed policy is wrong.
- Partner site direct API calls fail with CORS:
  - Add partner origin to `CORS_ALLOWED_ORIGINS` (separate from iframe settings).

Use the lightweight validation assets to confirm header behavior:

- Checklist: [docs/EMBED_VALIDATION.md](docs/EMBED_VALIDATION.md)
- Script: `powershell -ExecutionPolicy Bypass -File scripts/check-embed-policy.ps1 -BaseUrl https://localhost -ExpectedAllowedOrigins https://partner-a.example`

#### Post-upgrade verification
After updating compose templates or changing `.env`, run these checks to confirm nginx is receiving embed origins and serving the expected CSP:

```sh
docker compose up -d --force-recreate nginx
docker exec aft-web sh -lc 'echo "EMBED_ALLOWED_ORIGINS=$EMBED_ALLOWED_ORIGINS"'
docker exec aft-web cat /etc/nginx/snippets/embed_frame_ancestors.inc
curl -I "https://<your-aft-host>/public-board.html?slug=<your-public-slug>"
```

Expected results:

- `EMBED_ALLOWED_ORIGINS` inside `aft-web` is non-empty.
- `embed_frame_ancestors.inc` includes your allowlisted origins after `'self'`.
- `Content-Security-Policy` on `/public-board.html` includes `frame-ancestors` with the same origins.

### HTTPS and Session Cookie Security
By default, the stack now enforces secure session cookies and redirects direct HTTP requests to HTTPS.

- Nginx auto-generates a self-signed certificate at startup when no certificate files exist, so HTTPS works out of the box without manual certificate setup.
- Flask defaults `SESSION_COOKIE_SECURE=true`, so browsers only send session cookies over HTTPS.
- The HTTP listener (port 80) redirects non-localhost traffic to HTTPS unless an upstream reverse proxy forwards `X-Forwarded-Proto: https`.

This keeps direct deployments secure by default while still supporting external reverse proxies and certificate resolvers.

### Passkeys
Users can sign in with a passkey (fingerprint, face, screen lock, a password manager, or a security key) instead of typing their password. Passkeys are an alternative way to sign in, not a second factor, and every account keeps its password.

Passkeys are **off until you set `WEBAUTHN_RP_ID`**. Once they are on:
- users add and manage passkeys from their **Profile** page (adding one asks for their current password)
- the login page shows a **Sign in with a passkey** button, and supported browsers also offer saved passkeys when you click the username field
- administrators can revoke all of a user's passkeys from **User Management**, for example after a lost device

#### Before you turn them on
Browsers only allow passkeys when all of these are true:
- **AFT is reached by a domain name**, such as `aft.example.com`. Passkeys don't work when you browse to an IP address (`https://192.168.1.10`). Single-word LAN host names (`https://aft`) may not work in every browser.
- **The connection is HTTPS with a certificate the browser trusts.** Chrome and Edge turn passkeys off on pages with certificate errors, so the auto-generated self-signed certificate is not enough unless every device trusts it. Use a real certificate (for example from Let's Encrypt or your reverse proxy), or install your own CA on each device. `http://localhost` is the only exception, for development.
- **The domain stays the same.** Each passkey is tied to `WEBAUTHN_RP_ID`. If you change it later, or move AFT to a different domain, every existing passkey stops working and users must add new ones. Their passwords keep working.

#### Settings
Add these to `.env` and restart the server (`docker compose up -d server`). An invalid value stops the server at startup with a message saying what is wrong.

| `.env` variable | Required | Default | What it does |
|---|---|---|---|
| `WEBAUTHN_RP_ID` | Yes, to turn passkeys on | (unset: passkeys off) | The domain passkeys are tied to, with no `https://`, port or path. For example `aft.example.com`. It can be a parent domain (`example.com`) if AFT is served from several subdomains of it. |
| `WEBAUTHN_ORIGINS` | No | `https://<WEBAUTHN_RP_ID>` | Comma-separated list of the exact addresses users open AFT at, including any port, for example `https://aft.example.com,https://aft.example.com:8443`. Each must be on `WEBAUTHN_RP_ID` or a subdomain of it, and must be `https` (only `http://localhost` is allowed for development). |
| `WEBAUTHN_RP_NAME` | No | `AFT` | The name browsers and password managers show next to the passkey. Up to 64 characters. |

Passkey sign-in also needs Redis (`REDIS_URL`), which the standard compose files already provide.

Example for a site at `https://boards.example.com`:

```
WEBAUTHN_RP_ID=boards.example.com
```

Example for local development at `http://localhost`:

```
WEBAUTHN_RP_ID=localhost
WEBAUTHN_ORIGINS=http://localhost,https://localhost
```

#### Notes
- Revoking a user's passkeys ends any sessions that were signed in with them. Sessions signed in with a password continue, so also reset the user's password if a device was lost or stolen.
- A user who removes a passkey from their Profile page should also delete it from their device or password manager, or it will keep being offered on the login page.
- Two-factor authentication is a separate feature, tracked in [#587](https://github.com/sjefferson99/aft/issues/587).

### Database memory tuning
The `db` service runs MySQL with settings sized for small self-hosted installs. Stock MySQL defaults suit a dedicated database server, and in AFT they used 450–600 MB at idle. With the defaults below, idle memory is about 130 MB.

Every setting can be overridden in `.env` with the variable shown. Each is commented out in [.env.example](.env.example), and `compose.yml` / `compose.example.yml` pass them to MySQL as command-line options with these defaults:

| `.env` variable | MySQL option | Default | MySQL stock | What it does / when to change it |
|---|---|---|---|---|
| `MYSQL_INNODB_BUFFER_POOL_SIZE` | `innodb_buffer_pool_size` | `32M` | `128M` | Caches table and index data in memory. 32 MB holds a typical AFT database. If your data is larger, raise it to at least the data size (see the query below) so reads come from memory. This is the main setting for larger installs. |
| `MYSQL_MAX_CONNECTIONS` | `max_connections` | `100` | `151` | Maximum concurrent client connections. Each gunicorn worker process can open up to 15 (SQLAlchemy pool of 5 plus overflow of 10), and backups and restores open a few more. Keep it above `15 × workers + 10`. If you see `Too many connections` errors, raise it. |
| `MYSQL_MAX_ALLOWED_PACKET` | `max_allowed_packet` | `128M` | `64M` | Largest single SQL statement or row MySQL accepts. Backups are restored as SQL, so if a restore fails with a `Got a packet bigger than 'max_allowed_packet'` error, raise it (for example to `256M`). |
| `MYSQL_INNODB_LOG_BUFFER_SIZE` | `innodb_log_buffer_size` | `4M` | `64M` | Buffers redo-log writes before they reach disk. AFT's writes are small. Raise it only if very large imports or restores are slow. |
| `MYSQL_TABLE_OPEN_CACHE` | `table_open_cache` | `200` | `4000` | Number of open table handles cached across sessions. AFT has under 20 tables, so 200 leaves plenty of headroom. You should not need to change it. |
| `MYSQL_PERFORMANCE_SCHEMA` | `performance_schema` | `OFF` | `ON` | MySQL's internal instrumentation, and the largest single memory consumer (~190 MB). AFT does not use it. Set it to `ON` only to diagnose MySQL performance problems. |

To check your data size, from the docker host:

```sh
docker exec aft-db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024) AS size_mb FROM information_schema.tables WHERE table_schema = \"$MYSQL_DATABASE\";"'
```

Example `.env` overrides for a larger install running 4 gunicorn workers (`GUNICORN_WORKERS=4`, see [Server workers and threads](#server-workers-and-threads)):

```sh
MYSQL_INNODB_BUFFER_POOL_SIZE=256M
MYSQL_MAX_CONNECTIONS=150
```

Apply changes by recreating the database container with `docker compose up -d db`. A plain `docker compose restart` does not pick up `.env` changes. The settings need no data migration, so existing data directories are unaffected. To confirm the values in effect:

```sh
docker exec aft-db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SELECT @@innodb_buffer_pool_size, @@max_connections, @@max_allowed_packet, @@innodb_log_buffer_size, @@table_open_cache, @@performance_schema;"'
```

If `aft-db` keeps restarting after a change, a value is probably invalid (for example `100O` instead of `100`). MySQL names the bad option in its log, which you can see with `docker compose logs db`. Fix the value in `.env` and run `docker compose up -d db` again.

> **Upgrading from an older compose file:** these options live in the `command:` list of the `db` service. Merge that block from the latest `compose.example.yml` into your `compose.yml`, or the `.env` variables have no effect.

### Server workers and threads
The `server` container runs gunicorn with **1 worker process and 32 threads** by default. Idle memory is about 110 MB; the previous fixed setting of 4 workers × 8 threads used about 340 MB. You can change both values in `.env`:

| `.env` variable | Default | Allowed | What it does / when to change it |
|---|---|---|---|
| `GUNICORN_THREADS` | `32` | 1–128 | Threads per worker. Every open board or theme-builder tab keeps a live WebSocket connection that holds one thread for as long as it's open, and normal API requests share the rest. The thread count is therefore roughly the number of tabs one worker can serve at once. Threads cost very little memory (1 × 64 idles at the same ~110 MB as 1 × 32). If you regularly have more than about 25 tabs open, raise this first. |
| `GUNICORN_WORKERS` | `1` | 1–16 | Worker processes. Each extra worker adds about 80 MB, and it multiplies the thread count (workers × threads). One worker handles a typical self-hosted install. Add workers only if one worker's CPU becomes a bottleneck, for example many concurrent active users. Python runs only one thread at a time per process, so extra workers add CPU parallelism and extra threads don't. |

**If you add workers, check MySQL's connection limit.** Each worker can open up to 15 database connections, so `MYSQL_MAX_CONNECTIONS` must be above `15 × GUNICORN_WORKERS + 10` (see [Database memory tuning](#database-memory-tuning)). The default limit of 100 covers up to 6 workers. If the limit is too low, the server logs a warning at startup that gives the value to set.

Example `.env` for a busier install:

```sh
GUNICORN_WORKERS=2
GUNICORN_THREADS=64
```

Apply changes with `docker compose up -d server`. Invalid values, such as `0`, `abc` or anything outside the allowed range, stop the server from starting. The reason appears in `docker compose logs server`, for example `Invalid gunicorn setting: GUNICORN_WORKERS must be a whole number between 1 and 16, got '4O'`.

Multi-worker support is unchanged. Socket.IO broadcasts go through Redis, and the schedulers use file and database locks, so raising `GUNICORN_WORKERS` needs no other configuration.

**During a large database restore** with a single worker, other requests can slow to a few seconds while the backup file is read and validated, because that work runs in the same process. Requests return `503` while the database itself is being reloaded, whatever the worker count. The only exception is the progress route the restore page polls, `GET /api/database/restore/progress/<id>`, which doesn't use the database. In testing, a 75 MB restore took about 25 seconds in total.

### Sign-in rate limits
AFT slows down password guessing. After too many failed attempts, further attempts get a "Too many attempts" message until the block ends. Blocks end by themselves, and people who are already signed in aren't affected. A blocked account can still sign in with a passkey. Failed passwords count across sign-in, password changes and adding a passkey, and only failures count. Limits apply to unknown usernames too, so a block doesn't show whether an account exists.

**If another reverse proxy, such as Traefik, sits in front of the bundled nginx, set `TRUSTED_PROXY_HOPS=2`.** Otherwise every user appears to come from that proxy's address and shares one per-IP limit, so failed attempts by one person could block everyone's sign-in. Use the real number of proxies: a value that is too high lets clients fake their address by sending their own `X-Forwarded-For` header. If you run the server without nginx and nothing in front of it, set `TRUSTED_PROXY_HOPS=0`.

| `.env` variable | Default | Allowed | What it does |
|---|---|---|---|
| `TRUSTED_PROXY_HOPS` | `1` | 0 or more | Proxies in front of the server, counting the bundled nginx. Used to find each client's real IP address. |
| `AUTH_RATE_LIMIT_ACCOUNT_FAILURES` | `10` | 1 or more | Failed password attempts per account in 15 minutes. |
| `AUTH_RATE_LIMIT_IP_FAILURES` | `50` | 1 or more | Failed password attempts per client IP in 15 minutes, across all accounts. Raise this if many people share one public address, such as an office network. |
| `AUTH_RATE_LIMIT_REGISTRATIONS` | `10` | 1 or more | Registration attempts per client IP in an hour. Signed-in administrators creating users aren't limited. |
| `AUTH_RATE_LIMIT_PASSKEY_STARTS` | `60` | 1 or more | Passkey sign-ins started per client IP in a minute. |

Apply changes with `docker compose up -d server`. Invalid values stop the server from starting, and the reason appears in `docker compose logs server`. Blocked attempts are logged as warnings in the same place.

Blocks survive a restart of Redis. To clear every block early, without signing anyone out, run:

```sh
docker compose exec redis sh -c "redis-cli --scan --pattern 'aft:rl:auth:*' | xargs -r redis-cli del"
```

### Backup Storage
Automatic backups are stored on the host filesystem at `./backups/` (relative to the docker-compose.yml location). This directory is automatically created by Docker and persists across container restarts. You can include this directory in your host backup solution for additional data protection.

**Permission Requirements**: The container runs as a non-root user (UID 1000). If the `./backups/` directory is not writable, backups will fail with a permission error displayed in the UI. To fix this, run:
```bash
sudo chown -R 1000:1000 ./backups
sudo chmod -R 755 ./backups
```

## Testing

For developers who want to run the test suite:

```powershell
cd server
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

**Note:** Tests automatically handle authentication by creating a test admin user. For detailed testing instructions including fresh database setup, see [server/docs/SERVER_TESTING.md](server/docs/SERVER_TESTING.md).

For browser-driven UI tests (Playwright, via pytest):

```bash
cd ui-tests
pip install -r requirements-dev.txt
playwright install chromium
pytest
```

See [ui-tests/docs/UI_TESTING.md](ui-tests/docs/UI_TESTING.md) for details.

For measuring board performance at scale (seeding a large board and comparing
server/client cost before and after a change), see [perf-tests/README.md](perf-tests/README.md).

## Contributing and Agent Context

If you are contributing code (human or AI-assisted), start with [CONTRIBUTING.md](CONTRIBUTING.md).

For portable, agent-specific project context that should be available across machines via git, use [AGENT_CONTEXT.md](AGENT_CONTEXT.md). Keep this file concise and focused on stable workflow/security/testing facts.


## Security and Access Control

The application includes a multi-user security model with authentication, role-based authorisation, and secure-by-default deployment settings.

- **Authentication Across HTTP + WebSocket** - Login/logout is enforced for protected API access and real-time socket connections.
- **Role-Based Access Control (RBAC)** - Supports global and board-specific roles with permission checks on backend endpoints.
- **Permission-Aware UI** - Frontend controls are shown/hidden based on effective permissions, reducing invalid actions before API calls.
- **Ownership and IDOR Protection** - Server-side scoping checks prevent users from accessing resources they do not own or are not assigned to.
- **Secure Session Defaults** - HTTPS-first behaviour, secure session cookies by default, and optional Redis-backed server-side sessions.
- **Passkeys (optional)** - Sign in with a passkey instead of a password, once an administrator sets the passkey domain. See [Passkeys](#passkeys).
- **Password Guessing Limits** - Repeated failed passwords are temporarily blocked per account and per client IP. See [Sign-in rate limits](#sign-in-rate-limits).
- **Operational Hardening** - Token-protected health checks and browser hardening headers in the reverse proxy layer.
- **Public Board Guardrails** - Anonymous access is limited to redacted read-only board payloads via slug URLs; private boards and all write/admin endpoints remain auth-gated.
- **Public Route Controls** - Public board endpoints include crawler-dissuasion/cache headers and request throttling to reduce abuse risk.

### Permissions Access Model and User Lifecycle

- **Board Ownership and Sharing** - Boards are owned by a user, and access can be shared per board. Board-specific roles enable read-only access (viewer) or read/write collaboration (editor) without granting global access to all boards. Board owners and administrators can reassign ownership from the board menu on the board page.
- **Fine-Grained Per-Board Permissions** - Effective permissions are evaluated per board, so actions like editing or deleting are allowed only where the user has board-level rights.
- **Custom Role Construction** - Role management supports building custom roles from individual permission blocks, then assigning those roles to users within the allowed assignment scope.
- **Controlled Role Assignment** - Role changes require role-management permissions, with backend checks to prevent unauthorised escalation and invalid global vs board-specific assignments.
- **Registration and Approval Workflow** - New user registrations are created in a pending state and must be approved by an administrator before login access is granted.
- **First Admin Initial Setup** - A dedicated setup flow creates the first administrator account, auto-approves it, and completes initial bootstrap for the instance.
- **Restore During Setup** - To move an existing instance, upload a backup on the first-time setup page instead of creating an account, then sign in with an account from the backup. This only works until setup is complete. If the restore fails, the instance returns to first-time setup.
- **User Profile Colours** - Each user is assigned a default avatar/profile colour (RGB hex) on account creation and can update it from the Profile page.

For implementation details and extension guidance:
- [server/docs/AUTHENTICATION.md](server/docs/AUTHENTICATION.md)
- [server/docs/PERMISSION_MODEL.md](server/docs/PERMISSION_MODEL.md)
- [docs/PERMISSION_UI_SYSTEM.md](docs/PERMISSION_UI_SYSTEM.md)

### Testing WebSocket Disconnection

To test the WebSocket disconnection scenario (for development/debugging):

1. Edit [server/app.py](server/app.py) and set `REJECT_SOCKETIO_CONNECTIONS` to `True`
2. Rebuild: `docker compose down ; docker compose up -d --build`
3. Open board page - header shows "WebSocket Disconnected" within 5 seconds
4. Real-time updates will not work
5. Revert `REJECT_SOCKETIO_CONNECTIONS` to `False` and rebuild to restore connectivity

### Polling & Real-Time Updates

- **Polling Interval**: Status checks happen every 5 seconds
- **Real-Time Events**: Socket.IO events (connect/disconnect) trigger immediate updates
- **Reconnection**: Socket.IO automatically retries failed connections with exponential backoff

## Architecture Decisions

Architecture rationale and implementation notes are maintained in [docs/Architecture.MD](docs/Architecture.MD).
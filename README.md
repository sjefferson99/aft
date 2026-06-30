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
Check the swagger docs page in the settings menu for more details.

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
- Existing boards keep their own working style and can be changed from each board's settings menu.

![Working Style Options](images/working_style_options.png)

**Available Options:**
- **Kanban** - Traditional column-based workflow where cards move through stages (To Do, In Progress, Done, etc.)
- **Agile** - Enables done tracking and a dedicated Done View on the board

In Agile mode, cards use Done/Not Done status and the Archived View is hidden. In Kanban mode, archive workflows remain available. For detailed information on using these features, see the Docs page (accessible from the user menu in the header).

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
- **AFT JSON** - Re-import any board exported from AFT, including columns, cards, checklists, comments, scheduled cards, and assignees
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
- **Public Visibility Toggle** - Board owners/editors can switch a board between private and public from the board settings menu.
- **Stable Share Link** - Making a board private and public again keeps the same public slug unless you explicitly rotate it.
- **Rotate Public Link** - Use "Rotate Public Link" in board settings to immediately invalidate the old URL and issue a new one.
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
- **Update Cards** - Edit card details, titles, and descriptions
- **Assign Responsibility** - Set a primary assignee and optional secondary assignees per card from users with board access
- **Assignee Avatars** - Cards show the primary assignee initials in a bottom-left avatar circle using the assignee's profile colour
- **Board Assignee Filters** - Open/toggle the compact assignee filter bar from the header search field's filter icon to show cards for selected assignees, include unassigned cards, and optionally match secondary assignees. When filters are active, a visual indicator appears next to the board name. Clear all filters quickly via the settings menu "Clear filters" option.
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
  - **Board-Level Override**: Existing board style is managed from that board's settings menu
  - **Done Button**: Mark cards as complete without moving them between columns in Agile mode
  - **Done View**: Dedicated view to see completed cards in Agile mode
  - **Archived View**: Available in Kanban mode; hidden in Agile mode
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

![Backup Settings](images/backup_configuration.png)

### � Documentation
- **Comprehensive Docs** - Full documentation available in-app via the Docs page
- **Keyboard Shortcuts** - Quick reference for card creation shortcuts (N for top, M for bottom)
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
  - Prevents duplicate notifications for the same version
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
- **Operational Hardening** - Token-protected health checks and browser hardening headers in the reverse proxy layer.
- **Public Board Guardrails** - Anonymous access is limited to redacted read-only board payloads via slug URLs; private boards and all write/admin endpoints remain auth-gated.
- **Public Route Controls** - Public board endpoints include crawler-dissuasion/cache headers and request throttling to reduce abuse risk.

### Permissions Access Model and User Lifecycle

- **Board Ownership and Sharing** - Boards are owned by a user, and access can be shared per board. Board-specific roles enable read-only access (viewer) or read/write collaboration (editor) without granting global access to all boards. Board owners and administrators can reassign ownership from the board header settings menu on the board page.
- **Fine-Grained Per-Board Permissions** - Effective permissions are evaluated per board, so actions like editing or deleting are allowed only where the user has board-level rights.
- **Custom Role Construction** - Role management supports building custom roles from individual permission blocks, then assigning those roles to users within the allowed assignment scope.
- **Controlled Role Assignment** - Role changes require role-management permissions, with backend checks to prevent unauthorised escalation and invalid global vs board-specific assignments.
- **Registration and Approval Workflow** - New user registrations are created in a pending state and must be approved by an administrator before login access is granted.
- **First Admin Initial Setup** - A dedicated setup flow creates the first administrator account, auto-approves it, and completes initial bootstrap for the instance.
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
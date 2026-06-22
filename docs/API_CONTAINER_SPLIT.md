# Deployment Plan: Enable Headless AFT-Server with Remote UI Support

## Overall Aim

Transform AFT from a coupled single-host stack into a flexible multi-deployment architecture that supports:

1. **Headless API Server** — Self-contained aft-server with database, Redis, and API endpoints that can run independently without UI
2. **Remote UI Connectivity** — Static UI instances that can connect to any configured aft-server over HTTPS
3. **Multi-Server Infrastructure** — Enable Ansible-managed deployments where multiple headless servers serve different teams/projects with shared or dedicated UIs
4. **Production-Ready Cross-Origin** — Proper CORS, TLS, and session cookie configuration for secure internet-facing deployments

**Non-Goals (Explicitly Deferred):**
- JWT Bearer token authentication (future enhancement, not required for cross-origin)
- CSRF tokens (mitigated by CORS whitelisting + HTTPS; tokens can be added later without breaking changes)
- External IDP integration (future enhancement, model already prepared)
- Mobile app support (enabled by future Bearer tokens)
- Web UI for configuration management (infrastructure-as-code via .env is industry standard)

## Success Criteria

- [ ] Existing single-host deployments continue working unchanged (compose.yml)
- [ ] New compose.server.yml deploys headless API-only stack
- [ ] New compose.ui.yml deploys UI-only stack that connects to remote server
- [ ] User can select server URL at login and connect to remote aft-server over HTTPS
- [ ] All API endpoints tested throughout (not just at end)
- [ ] Documentation covers all three deployment modes with examples
- [ ] CI/CD builds all required images and publishes to GHCR
- [ ] GHCR packages have separate READMEs (README.server.md for server/API, README.ui.md for UI)

---

## Phased Implementation (Single PR, Multiple Commits)

Each phase is a separate commit in one PR. Testing is integrated throughout, not deferred to the end.

---

### Phase 1: Backend Configuration Foundation

**Commit:** `feat: add environment variables for cross-origin deployment`

**Changes:**

This phase adds three environment variables that enable secure cross-origin deployments. Here's what each does:

#### 1. `AFT_HOSTNAME` (for nginx server_name directive)

**What it does:** Controls which domain names nginx will respond to. When you access a server, the browser sends a "Host" header (e.g., `Host: aft.example.com`). Nginx checks this against its `server_name` directive to decide whether to handle the request.

**Default:** `_` (underscore) — This is nginx's catch-all that accepts ANY hostname. Safe for development and single-host deployments where the hostname doesn't matter.

**Why we need it:** Production servers should explicitly list allowed hostnames to prevent:
- DNS rebinding attacks
- Accepting requests meant for other services
- Confusing logs/metrics from random bots hitting your IP

**Example usage:**
```bash
# Development (default) - accepts any hostname
AFT_HOSTNAME=_

# Production - specific domain only
AFT_HOSTNAME=aft.example.com

# Multiple domains (space-separated)
AFT_HOSTNAME=aft.example.com aft-prod.internal.company.com
```

**How it works:** In Phase 5 and 6, we create nginx Dockerfiles that use `envsubst` to inject this value into the nginx config file:
```nginx
server {
    server_name ${AFT_HOSTNAME};  # Gets replaced with actual value at container startup
    ...
}
```

---

#### 2. `AFT_SERVER_ORIGINS` (for UI Content Security Policy)

**What it does:** Tells the UI which backend servers it's allowed to connect to. This is enforced by the browser's Content Security Policy (CSP), specifically the `connect-src` directive that controls fetch() and WebSocket connections.

**Default:** Empty — The UI's CSP will default to `connect-src 'self'`, meaning it can only connect to the same origin it was loaded from (same-origin deployment).

**Why we need it:** When the UI is hosted separately from the API server (cross-origin deployment), the browser blocks API calls by default as a security measure. This variable whitelists specific backend servers.

**Example usage:**
```bash
# Same-origin deployment (default) - UI and API on same server
# No value needed, browser allows connections to 'self'

# Cross-origin deployment - UI on one server, API on another
AFT_SERVER_ORIGINS=https://api.aft.example.com

# Multiple API servers - UI can connect to any of them
AFT_SERVER_ORIGINS=https://api1.aft.example.com https://api2.aft.example.com https://api3.aft.example.com
```

**How it works:** In Phase 6, the UI nginx container uses `envsubst` to build its CSP header:
```nginx
# If AFT_SERVER_ORIGINS is empty, use 'self'
# If set, use 'self' + the configured origins
add_header Content-Security-Policy "default-src 'self'; connect-src 'self' ${AFT_SERVER_ORIGINS}; ...";
```

Browser enforces this when the UI tries to make API calls.

---

#### 3. `SESSION_COOKIE_SAMESITE` (for cross-origin authentication)

**What it does:** Controls when the browser sends session cookies with HTTP requests. This is a critical security setting that prevents CSRF attacks but also affects cross-origin functionality.

**Default:** `Lax` — This is the current behavior. Cookies are sent:
- ✅ When user navigates to the site (top-level navigation)
- ✅ When the UI is on the same domain as the API (same-origin)
- ❌ When the UI makes cross-origin requests (fetch from different domain)

**Why we need it:** For remote UI deployments, the UI and API are on different domains. With `SameSite=Lax`, the browser won't send session cookies with cross-origin fetch() calls, so login fails. We need the ability to configure `SameSite=None` for this scenario.

**Possible values:**
- `Lax` (default) — Same-origin only, most secure, recommended for single-host deployments
- `Strict` — Even stricter, not useful for this use case
- `None` — Allows cross-origin cookies, **requires HTTPS** (`SESSION_COOKIE_SECURE=True`)

**Security implications:**
- `Lax` or `Strict`: Protects against CSRF attacks automatically
- `None`: Opens up CSRF risk, so you MUST:
  - Use HTTPS (enforced by validation)
  - Configure CORS properly (limits which domains can make requests)
  - Consider adding CSRF tokens in future (not in this PR)

**Example usage:**
```bash
# Same-origin deployment (default) - most secure
SESSION_COOKIE_SAMESITE=Lax

# Cross-origin deployment - required for remote UI to work
SESSION_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=True  # Required when using None
```

**How it works:**
1. Flask sets this attribute when creating session cookies: `Set-Cookie: session=...; SameSite=Lax; ...`
2. Browser stores the cookie with the SameSite policy
3. When UI makes API request:
   - `Lax`: Browser checks if domains match, only sends cookie if same-origin
   - `None`: Browser always sends cookie (if HTTPS)
4. API receives cookie, authenticates user, returns data

**Validation added in this phase:**
```python
# In server/app.py
samesite = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
secure = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() == 'true'

if samesite == 'None' and not secure:
    raise ValueError("SESSION_COOKIE_SAMESITE=None requires SESSION_COOKIE_SECURE=True for security")

if samesite == 'None':
    logger.warning("Cross-origin mode enabled (SameSite=None). Ensure CORS is properly configured.")
```

---

#### Why Not CSRF Tokens?

**Short answer:** CSRF tokens are a future enhancement, not required for this PR to be secure.

**Long answer:** 

With `SameSite=Lax` (default, same-origin deployment):
- Browser automatically blocks CSRF attacks
- No tokens needed

With `SameSite=None` (cross-origin deployment):
- CSRF protection is weakened
- However, we have **layered mitigations**:
  1. **CORS whitelisting** — Only configured origins can make requests (blocks random websites)
  2. **HTTPS enforcement** — Prevents MitM tampering with cookies
  3. **Session validation** — Every request validates the session server-side
  4. **Origin checking** — Browser sends Origin header, server can validate (not implemented yet but infrastructure exists)

**Why defer CSRF tokens:**
- Adds complexity (token generation, validation, UI changes to include tokens)
- Not a blocker for secure deployment if CORS is properly configured
- Most important for public-facing deployments; many users will deploy on internal networks with VPN
- Can be added later without breaking changes

**Recommended timeline:**
- **This PR:** Get cross-origin deployments working securely with CORS + HTTPS
- **Next PR:** Add CSRF token middleware using Flask-WTF
- **Future:** Move to JWT Bearer tokens (eliminates cookie security concerns entirely)

**Immediate mitigation for paranoid deployments:**
- Keep `SameSite=Lax` and use VPN/Tailscale/Cloudflare Tunnel to make "remote" servers appear same-origin
- Rely on network-level access control (firewall, VPN, mutual TLS)

---

**Summary of changes:**
- Add `AFT_HOSTNAME` env var support in preparation for nginx config injection (Phases 5-6)
- Add `AFT_SERVER_ORIGINS` env var support in preparation for UI CSP configuration (Phase 6)
- Add `SESSION_COOKIE_SAMESITE` env var support to `server/app.py` with validation
- Update `.env.example` with all three variables and comprehensive usage documentation (include the explanations above)

**Testing:**
- Add pytest test for `SESSION_COOKIE_SAMESITE` validation (fails if `None` without `Secure`)
- Add pytest test that default `Lax` behavior unchanged
- Verify existing test suite passes
- Manual test: `docker compose up -d --build`, verify app starts, login works

**Verification:**
```bash
# All existing deployments work unchanged
docker compose down
docker compose up -d --build
# Navigate to https://localhost, verify login/boards work
```

**Files Modified:**
- `server/app.py` — add SESSION_COOKIE_SAMESITE config
- `.env.example` — add AFT_HOSTNAME, AFT_SERVER_ORIGINS, SESSION_COOKIE_SAMESITE with docs
- `server/tests/test_api_auth.py` — add SameSite validation tests

---

### Phase 2: Admin Configuration Visibility

**Commit:** `feat: add read-only CORS configuration endpoint`

**Changes:**
- Add `GET /api/settings/cors-origins` endpoint (admin-only)
- Returns `{ "origins": [...] }` from current `cors_allowed_origins` list
- Add Flasgger Swagger documentation
- Add to `settings_routes.py` or create dedicated endpoint

**Testing:**
- Add pytest test for endpoint (admin can access, returns origins list)
- Add pytest test that non-admin gets 403
- Add pytest test for empty origins case
- Verify with curl: `curl -H "Authorization: Basic admin@localhost:password" https://localhost/api/settings/cors-origins`

**Verification:**
```bash
# Run pytest after changes
cd server
..\.venv\Scripts\python.exe -m pytest tests/test_api_settings.py -k cors_origins -v
```

**Files Modified:**
- `server/settings_routes.py` — add GET /api/settings/cors-origins endpoint
- `server/tests/test_api_settings.py` — add test coverage

---

### Phase 3: Frontend API Client Abstraction

**Commit:** `refactor: add centralized AftClient API module`

**Changes:**
- Create `www/js/aft-client.js` with:
  - `AftClient.getServerUrl()` → returns `localStorage.getItem('aft_server_url') || window.location.origin`
  - `AftClient.setServerUrl(url)` → saves to localStorage
  - `AftClient.apiFetch(path, options)` → wraps fetch with server URL prefix
  - `AftClient.connectSocket(options)` → wraps io() with server URL
  - Complete JSDoc comments
- Update all HTML files to load `aft-client.js` before other scripts

**Testing:**
- Manual smoke test: verify all pages load
- Console check: `AftClient` object exists
- Console check: `AftClient.getServerUrl()` returns `window.location.origin`
- No functional changes yet (module loaded but not used)

**Verification:**
```bash
# Rebuild and test
docker compose up -d --build
# Open browser dev console on any page
# Type: AftClient.getServerUrl()
# Should return: "https://localhost" or current origin
```

**Files Modified:**
- `www/js/aft-client.js` — new file
- All HTML files in `www/` — add script tag before other JS includes

---

### Phase 4: Frontend API Call Migration

**Commit:** `refactor: migrate all fetch and Socket.IO calls to AftClient`

**Changes:**
- Replace all `fetch('/api/...')` with `AftClient.apiFetch('/api/...')` across all JS files
- Replace `io({...})` with `AftClient.connectSocket({...})` in board.js
- Remove `credentials: 'include'` from fetch calls (prepare for future Bearer tokens)

**Testing:**
- Full functional test of all pages:
  - Login/logout
  - Board list, create board
  - View board, create/move/delete cards
  - Settings pages (users, roles, themes, backups)
  - Profile, notifications
  - WebSocket real-time updates (move card on one browser tab, verify update in another)
- Run full pytest suite to catch any API regressions
- Check browser console for any fetch errors

**Verification:**
```bash
# Rebuild
docker compose up -d --build

# Test checklist:
# [ ] Login works
# [ ] Boards page loads
# [ ] Create new board
# [ ] Add cards to board
# [ ] Move card between columns
# [ ] Open second browser tab, verify real-time update
# [ ] Settings > Users page loads
# [ ] Backup page loads
# [ ] Theme builder loads
# [ ] Logout works
```

**Files Modified:**
- `www/js/header.js`
- `www/js/board.js`
- `www/js/boards.js`
- `www/js/backup-restore.js`
- `www/js/login.js`
- `www/js/register.js`
- `www/js/settings.js`
- `www/js/user-management.js`
- `www/js/role-management.js`
- `www/js/profile.js`
- `www/js/theme-builder.js`
- `www/js/notifications.js`
- `www/js/system-info.js`

---

### Phase 5: API Nginx Container

**Commit:** `feat: add Dockerfile.api-nginx for headless server deployments`

**Changes:**
- Create `server/Dockerfile.api-nginx` based on `nginx:1.31-alpine`
- Create `server/nginx.api.conf`:
  - Proxy `/api/` and `/socket.io/` to Flask backend
  - No static file serving (return 404 for other paths)
  - TLS/HTTPS with self-signed fallback
  - Security headers (HSTS, CSP for API responses, X-Frame-Options)
  - WebSocket upgrade support
- Create/update `server/entrypoint.api.sh`:
  - Support `envsubst` for `${AFT_HOSTNAME}` injection into `server_name`
  - Auto-generate self-signed cert if no volume-mounted cert present
  - Check `/etc/nginx/ssl/cert.pem` and `/etc/nginx/ssl/key.pem` before generating

**Testing:**
- Build test: `docker build -f server/Dockerfile.api-nginx -t aft-api-nginx:test .`
- No runtime testing yet (not used in compose)

**Verification:**
```bash
# Build succeeds
docker build -f server/Dockerfile.api-nginx -t aft-api-nginx:test .
# Inspect image
docker run --rm aft-api-nginx:test ls -la /etc/nginx/conf.d/
```

**Files Created:**
- `server/Dockerfile.api-nginx`
- `server/nginx.api.conf`
- `server/entrypoint.api.sh`

---

### Phase 6: UI Nginx Container

**Commit:** `feat: add Dockerfile.ui-nginx for standalone UI deployments`

**Changes:**
- Create `server/Dockerfile.ui-nginx` based on `nginx:1.31-alpine`
- Create `server/nginx.ui.conf`:
  - Serve static files from `/usr/share/nginx/html` (www/ baked into image)
  - No `/api/` or `/socket.io/` proxy locations
  - CSP `connect-src` configured via `${AFT_SERVER_ORIGINS}` using envsubst
  - TLS/HTTPS with self-signed fallback
  - Static asset caching rules maintained
- Create/update `server/entrypoint.ui.sh`:
  - Support `envsubst` for `${AFT_SERVER_ORIGINS}` injection into CSP
  - Default to `'self'` if env var empty
  - Auto-generate self-signed cert if no volume-mounted cert present

**Testing:**
- Build test: `docker build -f server/Dockerfile.ui-nginx -t aft-ui-nginx:test .`
- No runtime testing yet (not used in compose)

**Verification:**
```bash
# Build succeeds
docker build -f server/Dockerfile.ui-nginx -t aft-ui-nginx:test .
# Inspect image
docker run --rm aft-ui-nginx:test ls -la /usr/share/nginx/html/
```

**Files Created:**
- `server/Dockerfile.ui-nginx`
- `server/nginx.ui.conf`
- `server/entrypoint.ui.sh`

---

### Phase 7: Server Selection UI

**Commit:** `feat: add server URL selection to login page and header display`

**Changes:**

**Login Page (www/login.html + www/js/login.js):**
- Add "Server URL" input field above email field
- Pre-fill with `AftClient.getServerUrl()`
- Validate: must be `https://` or `http://localhost` or `http://127.0.0.1`
- On successful login, call `AftClient.setServerUrl(inputValue)`
- Add help text: "Connect to a remote AFT server (leave as default for this server)"
- Add error display for invalid server URLs

**Header Display (www/js/header.js):**
- Update system-info dropdown to show current server
- Display format: "Connected to: {serverUrl}"
- Add "(this server)" indicator when `getServerUrl() === window.location.origin`
- Use `AftClient.getServerUrl()` to retrieve

**Testing:**
- Manual test login with various server URLs:
  - Default (window.location.origin) — should work
  - `https://localhost` — should work
  - `http://localhost` — should work
  - `http://example.com` — should show error (HTTP not allowed except localhost)
  - `https://example.com` — should accept (will fail to connect but validates correctly)
- Verify server URL persists after login (localStorage)
- Verify header displays current server correctly
- Verify "(this server)" indicator shows for same-origin

**Verification:**
```bash
docker compose up -d --build
# Test in browser:
# 1. Open login page, verify "Server URL" field present
# 2. Try invalid URL (http://example.com), verify error
# 3. Login with default, verify works
# 4. Check header, verify shows "Connected to: https://localhost (this server)"
```

**Files Modified:**
- `www/login.html` — add server URL input field
- `www/js/login.js` — add validation and localStorage save
- `www/css/login.css` — style server URL field (if needed)
- `www/js/header.js` — add server display to system-info dropdown

---

### Phase 8: UI System-Info CORS Display

**Commit:** `feat: add CORS origins display to system-info page`

**Changes:**
- Update `www/system-info.html` and `www/js/system-info.js`
- Add "CORS Configuration" section (admin-only visibility using existing permission checks)
- Fetch from `GET /api/settings/cors-origins` (added in Phase 2)
- Display origins as bulleted list
- Show "Not configured (localhost only)" if empty
- Handle API errors gracefully

**Testing:**
- Login as admin, verify CORS section appears
- Login as non-admin, verify CORS section hidden
- Verify origins display correctly
- Test with `CORS_ALLOWED_ORIGINS=https://example.com,https://test.com`, verify both shown

**Verification:**
```bash
# Set CORS in .env
echo "CORS_ALLOWED_ORIGINS=https://example.com,https://test.com" >> .env
docker compose up -d --build

# Login as admin, navigate to system-info page
# Verify CORS section shows both origins
```

**Files Modified:**
- `www/system-info.html` — add CORS section (conditionally rendered)
- `www/js/system-info.js` — fetch and display CORS origins

---

### Phase 9: Compose File Split

**Commit:** `feat: add compose.server.yml and compose.ui.yml for split deployments`

**Changes:**

**Create compose.server.yml (headless API server):**
- Services: db, redis, server, api-nginx (using Dockerfile.api-nginx)
- api-nginx depends on server (healthy)
- Expose ports 80, 443 on api-nginx
- Pass `AFT_HOSTNAME` env var to api-nginx
- Volume mount for TLS certs: `./ssl:/etc/nginx/ssl:ro`
- No www/ volume mount (no static files needed)

**Create compose.ui.yml (static UI only):**
- Single service: ui-nginx (using Dockerfile.ui-nginx)
- Expose ports 80, 443
- Pass `AFT_SERVER_ORIGINS` env var for CSP configuration
- Volume mount for TLS certs: `./ssl:/etc/nginx/ssl:ro`
- No backend services

**Keep compose.yml unchanged** (all-in-one dev default)

**Testing:**
- Build test for server stack:
  ```bash
  docker compose -f compose.server.yml build
  docker compose -f compose.server.yml up -d
  # Wait for healthy
  curl -k https://localhost/api/health/ready
  docker compose -f compose.server.yml down
  ```
  
- Build test for UI stack:
  ```bash
  docker compose -f compose.ui.yml build
  docker compose -f compose.ui.yml up -d
  curl -k https://localhost/
  # Should serve index.html
  curl -k https://localhost/api/auth/me
  # Should 404 (no API proxy)
  docker compose -f compose.ui.yml down
  ```

**Verification:**
```bash
# Test all three stacks independently

# 1. All-in-one (unchanged)
docker compose down
docker compose up -d --build
# Verify login works
docker compose down

# 2. Headless server
docker compose -f compose.server.yml up -d --build
# Verify API responds: curl -k https://localhost/api/health/ready
# Verify UI 404s: curl -k https://localhost/ (should 404)
docker compose -f compose.server.yml down

# 3. UI only
docker compose -f compose.ui.yml up -d --build
# Verify UI serves: curl -k https://localhost/
# Verify API 404s: curl -k https://localhost/api/auth/me (should 404)
docker compose -f compose.ui.yml down
```

**Files Created:**
- `compose.server.yml`
- `compose.ui.yml`

---

### Phase 10: Documentation

**Commit:** `docs: add comprehensive deployment guide for all three modes`

**Changes:**

**Update README.md:**
- Add "Deployment Modes" section after Quick Start:
  - **All-in-One (compose.yml)** — Single-host development and small deployments
  - **Headless API Server (compose.server.yml)** — API-only for automation, multi-server infra
  - **Remote UI (compose.ui.yml)** — Static UI connecting to any aft-server
- Add "Cross-Origin Deployment" section:
  - CORS configuration requirements
  - SESSION_COOKIE_SAMESITE setup for cross-origin
  - Example `.env` values for split deployment
  - TLS certificate management (volume mount + Certbot example)
  - Security considerations
  - Troubleshooting common issues

**Update .env.example:**
- Ensure all new variables documented with examples:
  - `AFT_HOSTNAME` — for nginx server_name
  - `AFT_SERVER_ORIGINS` — for UI CSP connect-src
  - `SESSION_COOKIE_SAMESITE` — with cross-origin guidance

**Create docs/DEPLOYMENT_MODES.md** (optional detailed guide):
- Step-by-step setup for each deployment mode
- Multi-server infrastructure example with Ansible
- Certificate management patterns
- Network security considerations
- Example scenarios (single-host, remote UI, multi-headless)

**Update available images list in README:**
- `ghcr.io/sjefferson99/aft:latest` — Flask API server
- `ghcr.io/sjefferson99/aft-web:latest` — Monolithic nginx (for compose.yml)
- `ghcr.io/sjefferson99/aft-api-nginx:latest` — API-only nginx (for compose.server.yml)
- `ghcr.io/sjefferson99/aft-ui:latest` — UI-only nginx (for compose.ui.yml)

**Create separate GHCR package READMEs:**
- Create `README.server.md` for server/API deployment:
  - Covers headless server stack (compose.server.yml)
  - Documents aft, aft-api-nginx, and aft-web images
  - Environment variables required
  - Security best practices
  - Example deployment scenarios
- Create `README.ui.md` for UI-only deployment:
  - Covers UI-only stack (compose.ui.yml)
  - Documents aft-ui image
  - Configuration for connecting to remote servers
  - CORS and CSP requirements
  - Example multi-server setup

These READMEs will be used by GitHub Actions to populate GHCR package descriptions (configured in Phase 11).

**Add OCI labels to Dockerfiles:**
- Update `server/Dockerfile` (Flask server):
  - Add `LABEL org.opencontainers.image.source="https://github.com/sjefferson99/aft"`
  - Add `LABEL org.opencontainers.image.licenses="MIT"`
- Update `server/Dockerfile.api-nginx`:
  - Add `LABEL org.opencontainers.image.source="https://github.com/sjefferson99/aft"`
  - Add `LABEL org.opencontainers.image.licenses="MIT"`
- Update `server/Dockerfile.ui-nginx`:
  - Add `LABEL org.opencontainers.image.source="https://github.com/sjefferson99/aft"`
  - Add `LABEL org.opencontainers.image.licenses="MIT"`
- Update `server/Dockerfile.web` (if it exists, for monolithic nginx):
  - Add same labels

Note: The `org.opencontainers.image.description` label will be dynamically injected by GitHub Actions in Phase 11 using the appropriate README file.

**Testing:**
- Documentation review (no code changes)
- Verify all links work
- Verify examples are accurate
- Follow deployment guide manually to ensure instructions work

**Verification:**
```bash
# Follow README deployment steps for each mode
# Verify instructions are complete and accurate
```

**Files Modified:**
- `README.md` — add deployment modes and cross-origin sections
- `.env.example` — ensure all variables documented
- `docs/DEPLOYMENT_MODES.md` — create detailed guide (optional)
- `README.server.md` — create GHCR package README for server/API deployment
- `README.ui.md` — create GHCR package README for UI-only deployment
- `server/Dockerfile` — add OCI labels
- `server/Dockerfile.api-nginx` — add OCI labels
- `server/Dockerfile.ui-nginx` — add OCI labels
- `server/Dockerfile.web` — add OCI labels (if exists)

---

### Phase 11: CI/CD Updates

**Commit:** `ci: add GitHub Actions workflow for multi-image builds`

**Understanding the Package Structure:**

We build **4 Docker images** but present them as **2 logical deployment options**:

**Deployment Option 1: AFT-Server (Headless API Stack)**
- Pulled by: `docker compose -f compose.server.yml up`
- Contains:
  - `ghcr.io/sjefferson99/aft:latest` — Flask API server (unchanged)
  - `ghcr.io/sjefferson99/aft-api-nginx:latest` — Nginx reverse proxy for API only (new)
  - Plus: MySQL, Redis (from official Docker Hub images)
- GHCR README: `README.server.md` (emphasizes this is the complete headless stack)

**Deployment Option 2: AFT-UI (Standalone UI)**
- Pulled by: `docker compose -f compose.ui.yml up`
- Contains:
  - `ghcr.io/sjefferson99/aft-ui:latest` — Nginx serving static UI files (new)
- GHCR README: `README.ui.md` (explains connecting to remote servers)

**Legacy: All-in-One (Unchanged)**
- Pulled by: `docker compose up`
- Contains:
  - `ghcr.io/sjefferson99/aft:latest` — Flask API server (same as above)
  - `ghcr.io/sjefferson99/aft-web:latest` — Monolithic nginx (API + UI) (unchanged)
  - Plus: MySQL, Redis
- GHCR README: Main `README.md` (existing documentation)

**Why 4 images, not 2?**
- Docker images must be single-purpose (can't bundle nginx + Flask in one image without complexity)
- Compose files orchestrate multiple images into logical stacks
- Users don't pull individual images manually — they use compose files
- GHCR package pages will emphasize "use compose.server.yml" not "pull these 4 images"

---

**Changes:**
- Update `.github/workflows/docker-publish.yml` (or create if doesn't exist)
- Build and push four images on release:
  - `ghcr.io/sjefferson99/aft:latest` (Flask server — unchanged)
  - `ghcr.io/sjefferson99/aft-web:latest` (monolithic nginx — unchanged)  
  - `ghcr.io/sjefferson99/aft-api-nginx:latest` (API nginx — new)
  - `ghcr.io/sjefferson99/aft-ui:latest` (UI nginx — new)
- Tag all images with version number on release
- Add workflow step to verify all builds before push
- Configure GHCR package descriptions using separate READMEs:
  - Use `docker/metadata-action` to inject `org.opencontainers.image.description` label dynamically
  - Map images to READMEs:
    - `aft`, `aft-api-nginx` → use `README.server.md`
    - `aft-ui` → use `README.ui.md`
    - `aft-web` → use main `README.md` (legacy all-in-one)
  - GitHub Actions will sync README content to GHCR package pages
  - Each GHCR package page will show the compose file users should run

**Testing:**
- GitHub Actions runs on PR
- Verify all four images build successfully
- No push to GHCR on PR (only on release)

**Verification:**
```bash
# Create PR, verify CI passes
# Verify all four images build in Actions output
# After merge, verify images pushed to GHCR
```

**Files Modified:**
- `.github/workflows/docker-publish.yml` — update or create

---

### Phase 12: Final Integration Test

**Commit:** `test: add end-to-end cross-origin deployment test`

**Changes:**
- Add `server/tests/test_cross_origin_deployment.py` with integration tests (if appropriate)
- Add `docs/TESTING_SPLIT_DEPLOYMENT.md` with manual test plan

**Manual Test Plan:**
1. Deploy headless server on Server A (or localhost:8443)
2. Deploy UI on Server B (or localhost:9443)
3. Configure CORS on Server A to allow Server B origin
4. Configure SESSION_COOKIE_SAMESITE=None on Server A
5. Set AFT_SERVER_ORIGINS on Server B to Server A's origin
6. Access UI on Server B
7. Enter Server A URL in login form
8. Verify full functionality:
   - [ ] Login succeeds
   - [ ] Boards page loads
   - [ ] Create/edit/delete cards works
   - [ ] WebSocket real-time updates work
   - [ ] Settings pages work
   - [ ] Logout works
   - [ ] Re-login uses saved server URL

**Testing:**
- Follow manual test plan
- Document any issues found
- Verify split deployment works end-to-end

**Files Created:**
- `docs/TESTING_SPLIT_DEPLOYMENT.md` — manual test procedures

---

## Rollout Strategy

**Single PR Structure:**
- Title: `feat: enable headless server and remote UI deployments`
- Description: Links to this deployment plan, lists all 12 commits/phases
- Each phase is a separate commit with clear commit message
- Squash merge disabled — keep individual commits for bisect capability

**Merge Criteria:**
- [ ] All commits pass CI individually
- [ ] Full pytest suite passes
- [ ] Manual smoke test of all-in-one compose.yml works
- [ ] Manual test of compose.server.yml and compose.ui.yml successful
- [ ] Documentation reviewed and approved
- [ ] At least one successful cross-origin deployment test completed

**Rollback Plan:**
- If issues found post-merge, `git revert` specific commits
- All-in-one compose.yml unchanged, so existing deployments unaffected
- New compose files are opt-in, no breaking changes

---

## Post-Deployment

**Immediate Follow-up:**
- Monitor GitHub issues for deployment problems
- Update documentation based on user feedback
- Create FAQ section in docs for common questions

**Future Enhancements (Not in This PR):**
- **CSRF token middleware** — Add Flask-WTF CSRF protection for cross-origin deployments (currently mitigated by CORS + HTTPS)
- **JWT Bearer token authentication** — Better cross-origin support, eliminates cookie security concerns
- **External IDP integration** — Authentik, Keycloak, etc. via OIDC (model already prepared with oauth_provider fields)
- **Mobile app support** — Enabled by Bearer tokens
- **Admin UI for secrets management** — View/rotate API keys, session secrets
- **Prometheus metrics endpoint** — For monitoring headless servers

---

## Risk Assessment

**Low Risk:**
- Environment variable additions (all have defaults, backwards compatible)
- New compose files (opt-in, don't affect existing deployments)
- Documentation updates (no code impact)

**Medium Risk:**
- AftClient refactoring (large surface area, but mechanical changes)
- Mitigation: Comprehensive manual testing in Phase 4

**High Risk:**
- SESSION_COOKIE_SAMESITE changes for cross-origin
- Mitigation: Default to `Lax` (current behavior), `None` is opt-in
- Mitigation: Validation ensures secure configuration

**Testing Strategy:**
- Unit tests added in Phases 1 and 2
- Integration tests throughout (not just at end)
- Full functional test in Phase 4 (before any deployment changes)
- End-to-end cross-origin test in Phase 12

---

## Success Metrics

**Technical:**
- Zero regressions in existing compose.yml deployments
- All three compose stacks deploy successfully
- Cross-origin login and session management works
- WebSocket connections work across origins
- All pytest tests pass
- GHCR packages display appropriate READMEs (server vs UI documentation)

**User Experience:**
- Server selection is intuitive and works on first try
- Documentation enables users to deploy split stacks without support
- Error messages guide users to correct configuration

**Infrastructure:**
- CI builds all images successfully
- Images published to GHCR with correct tags
- Ansible playbooks can consume new compose files (future user validation)

# Contributing to AFT

Thank you for your interest in contributing to AFT. This document provides guidelines for contributing to the project.

## ⚠️ Pre-Submission Checklist

Before submitting any code contribution, **verify ALL items** are complete:

- [ ] **Authentication Setup** - If developing/testing features requiring authentication, ensure fresh database or test admin exists (see [Authentication for Development](#authentication-for-development))
- [ ] **Tests Created** - All new features and bug fixes MUST include tests (see [Testing Requirements](#testing-requirements))
- [ ] **API-Only Tests** - Tests use ONLY API endpoints, never direct database/filesystem access (see [SERVER_TESTING.md](server/docs/SERVER_TESTING.md))
- [ ] **UI Tests** - Changes to `www/` (HTML/CSS/JS) include a Playwright test covering the change (see [UI_TESTING.md](ui-tests/docs/UI_TESTING.md))
- [ ] **Code Standards** - Code follows all style guidelines in [Coding Standards](#coding-standards)
- [ ] **Frontend Error Handling** - All API calls follow error handling patterns (see [FRONTEND_ERROR_HANDLING.md](docs/FRONTEND_ERROR_HANDLING.md))
- [ ] **Swagger Documentation** - Every new Flask route has a Flasgger YAML docstring so it appears in `/api/docs` (see [API Documentation](#api-documentation))
- [ ] **Accessibility** - UI changes include ARIA attributes, keyboard navigation, screen reader support (see [Accessibility Requirements](#accessibility-requirements))
- [ ] **Security** - Input validation, length limits, no error leaking (see [Security Guidelines](#security-guidelines))
- [ ] **Database Changes** - Migration created, schema validation updated (see [Database Changes](#database-changes))
- [ ] **Documentation** - README/docs updated if behaviour changed
- [ ] **Agent Context Updated** - If workflow/security/testing behaviour changed, update [AGENT_CONTEXT.md](./AGENT_CONTEXT.md)
- [ ] **All Tests Pass** - Run `pytest -v` with fresh database and verify all tests pass

**AI Contributors:** Start with [AGENT_CONTEXT.md](./AGENT_CONTEXT.md), then read this entire document including all linked files (TESTING.md, ACCESSIBILITY.md, MIGRATION_GUIDE.md, FRONTEND_ERROR_HANDLING.md, AUTHENTICATION.md) before implementing ANY feature.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Human and Agent Documentation](#human-and-agent-documentation)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [API Documentation](#api-documentation)
- [Testing Requirements](#testing-requirements)
- [UI/E2E Testing Requirements](#uie2e-testing-requirements)
- [Accessibility Requirements](#accessibility-requirements)
- [Security Guidelines](#security-guidelines)
- [Pull Request Process](#pull-request-process)
- [Style Guide](#style-guide)
- [Commit Messages](#commit-messages)

## Code of Conduct

### Our Standards

- Use welcoming and inclusive language
- Be respectful of differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

I had copilot write all of this primarily so I can ensure it always does all the things. If you're manually contributing, ensure your PR follows the spirit of this guide, or better yet, have an AI do it for you, that's how this app works.

## Human and Agent Documentation

Use this section to keep documentation tidy and predictable for both humans and AI agents.

### Source of Truth for Agent-Specific Context

- Store agent-specific, high-signal context in [AGENT_CONTEXT.md](./AGENT_CONTEXT.md).
- Keep it concise and durable (workflow conventions, recurring pitfalls, stable security/testing facts).
- Do not store secrets or environment-specific private values in that file.

### What Goes Where

- Use [AGENT_CONTEXT.md](./AGENT_CONTEXT.md) for agent-oriented startup context and repeatable operational notes.
- Use human-facing docs (for example README, TESTING, SECURITY review docs, feature docs) for broader project documentation and reference material.
- If guidance is useful to both humans and agents, keep it in normal project docs and optionally summarize it in [AGENT_CONTEXT.md](./AGENT_CONTEXT.md).

### New Agent Session Setup

For any new Copilot/AI agent session in this repo:

1. Read [AGENT_CONTEXT.md](./AGENT_CONTEXT.md) first.
2. Read [CONTRIBUTING.md](./CONTRIBUTING.md) and linked policy documents.
3. After making workflow-impacting changes, update [AGENT_CONTEXT.md](./AGENT_CONTEXT.md) in the same PR.

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- Git
- A GitHub account

### Setting Up Development Environment

1. **Fork the Repository**
   
   Click the "Fork" button on the [AFT repository](https://github.com/sjefferson99/aft) to create your own copy.

2. **Clone Your Fork**
   
   ```bash
   git clone https://github.com/YOUR-USERNAME/aft.git
   cd aft
   ```

3. **Add Upstream Remote**
   
   ```bash
   git remote add upstream https://github.com/sjefferson99/aft.git
   ```

4. **Start Development Environment**
   
   ```bash
  docker compose up -d --build
   ```

  Important: For local development/testing, always use `compose.yml` with `--build`.
  `compose.example.yml` is the GHCR deployment template.

5. **Verify Setup**
   
   - Application: http://localhost:80
   - API: http://localhost/api/health

## Authentication for Development

**As of user support implementation, most API endpoints require authentication.** When developing or testing features:

### Initial Setup (First Time)

On a fresh database (no users exist), you can create an initial admin user:

1. Navigate to http://localhost/setup.html
2. Create your admin account
3. Use these credentials for development and testing

### Development Workflow

1. **Login to UI**: Navigate to http://localhost/login.html and login with your admin credentials
2. **API Testing**: Use browser dev tools or authenticated requests for API testing
3. **Session Management**: The system uses session-based authentication with cookies

### Running Tests

**Tests require a fresh database** to automatically create the test admin user. See [SERVER_TESTING.md](server/docs/SERVER_TESTING.md) for detailed instructions:

```powershell
# Windows
docker compose down
Remove-Item -Recurse -Force data
docker compose up -d --build

# Linux/macOS  
docker compose down
rm -rf data
docker compose up -d --build
```

Then run tests:
```powershell
cd server
.\venv\Scripts\Activate.ps1  # Windows
# or
source venv/bin/activate      # Linux/macOS

pytest -v
```

### Authentication Documentation

For detailed information about the authentication system:

- **[AUTHENTICATION.md](server/docs/AUTHENTICATION.md)** - Complete authentication architecture and implementation guide
- **[AUTH_QUICK_REFERENCE.md](server/docs/AUTH_QUICK_REFERENCE.md)** - Quick reference for using authentication in code
- **[SERVER_TESTING.md](server/docs/SERVER_TESTING.md)** - Test suite authentication requirements

## Development Workflow

### Quick Development Commands

Use these commands during local development and testing:

```bash
# Start/rebuild local dev stack from source
docker compose up -d --build

# Stop local dev stack
docker compose down

# Reset local DB state (remove host data dir contents)
docker compose down
rm -rf data   # Windows PowerShell: Remove-Item -Recurse -Force data
docker compose up -d --build

# Check service health/status
docker compose ps

# Tail logs across services
docker compose logs -f server nginx db redis

# Rebuild one service only
docker compose up -d --build server
```

### 1. Create an Issue

Before starting work, create an issue to document the problem or enhancement:

1. Go to the [Issues page](https://github.com/sjefferson99/aft/issues)
2. Click "New Issue"
3. Provide a clear title and description
4. Include:
   - Problem description or enhancement proposal
   - Your thoughts on potential fixes or implementation
   - Any relevant context, screenshots, or error messages
   - Acceptance criteria (what defines "done")

This helps coordinate work, avoid duplication, and gather feedback before implementation.

### 2. Create a Branch

Create a new branch for your feature or bugfix:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bugfix-name
```

### 3. Make Your Changes

- Write clean, maintainable code
- Follow the project's coding standards
- Add tests for new functionality
- Update documentation as needed
- Ensure accessibility requirements are met

### 4. Database Changes

**⚠️ IMPORTANT**: If your changes include database schema modifications (new tables, columns, etc.), follow these steps:

1. **Create Migration**: Follow the [Alembic Migration Guide](server/docs/MIGRATION_GUIDE.md)

2. **Update Schema Validation**: When adding new tables to the database:
   - Add the table name to the `expected_tables` list in the `validate_schema_integrity()` function in [server/app.py](server/app.py#L545)
   - This list defines which tables are allowed during backup restoration
   - Current expected tables: `alembic_version`, `boards`, `cards`, `checklist_items`, `columns`, `comments`, `notifications`, `scheduled_cards`, `settings`, `themes`
   - Failure to update this list will cause backup restoration to fail with "Unexpected tables found in backup" error

3. **Test Backup/Restore**: Verify backup and restore functionality works with your changes:
   - Create a manual backup using the Backup & Restore interface
   - Verify the backup file doesn't trigger security validation errors
   - Test restoring the backup to confirm it passes all validations

See the [Migration Guide](server/docs/MIGRATION_GUIDE.md) for detailed instructions on creating migrations and updating schema validation.

### 5. Test Your Changes

```bash
# Run all backend tests
cd server
pytest -v

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_api_boards.py -v
```

If your change touches `www/` (HTML/CSS/JS), also run the UI suite:

```bash
cd ui-tests
pytest -v
```

See [UI_TESTING.md](ui-tests/docs/UI_TESTING.md) for one-time setup
(`pip install -r requirements-dev.txt && playwright install chromium`).

### 6. Commit Your Changes

```bash
git add .
git commit -m "feat: add new feature"
```

See [Commit Messages](#commit-messages) for commit message guidelines.

### 7. Keep Your Branch Updated

```bash
git fetch upstream
git rebase upstream/main
```

### 8. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 9. Create a Pull Request

1. Go to your fork on GitHub
2. Click "Pull Request"
3. Select your branch
4. Fill out the PR template
5. Submit for review

## Coding Standards

### Python Code

- **Style**: Follow PEP 8
- **Formatting**: Use 4 spaces for indentation
- **Line Length**: Maximum 100 characters
- **Docstrings**: Use Google-style docstrings

```python
def example_function(param1: str, param2: int) -> dict:
    """Brief description of function.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Dictionary containing result
    
    Raises:
        ValueError: If param2 is negative
    """
    if param2 < 0:
        raise ValueError("param2 must be non-negative")
    
    return {"param1": param1, "param2": param2}
```

### JavaScript Code

- **Style**: Use ES6+ features
- **Formatting**: Use 2 spaces for indentation
- **Semicolons**: Use semicolons
- **Quotes**: Use single quotes for strings

```javascript
class ExampleClass {
  constructor() {
    this.property = 'value';
  }

  exampleMethod(param) {
    return `Result: ${param}`;
  }
}
```

### HTML/CSS

- **Indentation**: Use 2 spaces
- **Semantic HTML**: Use appropriate HTML5 elements
- **Accessibility**: Include ARIA attributes (see [Accessibility Requirements](#accessibility-requirements))
- **CSS Classes**: Use kebab-case for class names
- **Theme Variables Required**: Use existing CSS variables (for example primary/text/border/surface variables) for colors, spacing, and component states. Do not hardcode colors for new UI components.
- **Modal Consistency**: New modals must reuse existing modal structure and action patterns (`.modal`, `.modal-content`, `.modal-actions`, existing button styles) so they match the current UI and theme behavior.

## API Documentation

All Flask route functions **must** include a Flasgger YAML docstring so the endpoint appears in the interactive Swagger UI at `/api/docs`.

### Required Format

Every `@<blueprint>.route(...)` function must have a docstring with a one-line summary first, then a line containing `---` to begin valid Swagger 2.0 YAML:

```python
@some_bp.route("/api/example", methods=["POST"])
@require_authentication
def create_example():
    """Create a new example resource.
    ---
    tags:
      - Examples
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - name
          properties:
            name:
              type: string
    responses:
      201:
        description: Example created
      400:
        description: Missing or invalid fields
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
```

### Tag Conventions

Use consistent tags so related endpoints are grouped together in the UI:

| Tag | Use for |
|---|---|
| `Boards` | Board CRUD and import/export |
| `Cards` | Card operations |
| `Columns` | Column operations |
| `Notifications` | Notification endpoints |
| `Settings` | User and board settings |
| `Themes` | Theme management |
| `Health` | Liveness, readiness and stats |
| `Admin` | Debug, test-user and permission mapping |
| `Users` | User profile and management |
| `Auth` | Login, logout and session |
| `Roles` | Role and permission management |
| `Backups` | Backup management |
| `Schedules` | Scheduled card management |

### Security Declaration

- Authenticated endpoints must include `security:\n  - session: []`.
- Public endpoints (no auth required) omit the `security` block.

### Verification

Run the following to check for any routes missing a Swagger docstring before committing:

```bash
cd server
python3 -c "
import ast, pathlib
missing = []
for path in sorted(pathlib.Path('.').glob('*.py')):
    try: tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError: continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef): continue
        is_route = any(
            (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == 'route') or
            (isinstance(d, ast.Attribute) and d.attr == 'route')
            for d in node.decorator_list)
        if is_route and '---' not in (ast.get_docstring(node) or ''):
            missing.append(f'{path.name}:{node.lineno}  {node.name}()')
print(f'{len(missing)} routes missing Swagger YAML:')
for m in missing: print(' ', m)
"
```

Output should be `0 routes missing Swagger YAML`.

## Background Services

For features requiring scheduled or periodic operations, implement them as **daemon threads within the Flask app** rather than separate services.

### Service Architecture
- Create standalone Python scripts in server directory (e.g., `card_scheduler.py`, `backup_scheduler.py`)
- Implement a `get_scheduler()` function that returns a threading.Thread instance
- Use daemon threads so they terminate when the Flask app stops
- Use while True loop with sleep interval for scheduling
- Implement lock files to prevent issues if app restarts during execution
- Include comprehensive error handling and logging

### Example Scheduler Implementation

```python
import threading
import time
import os
from pathlib import Path

_scheduler_thread = None
_scheduler_lock = threading.Lock()

def run_scheduled_task():
    """Main scheduler loop."""
    lock_file = Path("/tmp/my_scheduler.lock")
    
    while True:
        try:
            # Check if already running (lock file exists)
            if lock_file.exists():
                logger.warning("Scheduler already running, skipping")
                time.sleep(60)
                continue
            
            # Create lock file
            lock_file.touch()
            
            try:
                # Perform scheduled task
                logger.info("Running scheduled task")
                # ... task logic here ...
                
            finally:
                # Always remove lock file
                if lock_file.exists():
                    lock_file.unlink()
            
        except Exception as e:
            logger.error(f"Error in scheduled task: {str(e)}")
            # Continue running despite errors
        
        # Wait before next iteration
        time.sleep(60)  # 60 seconds

def get_scheduler():
    """Get or create the scheduler thread."""
    global _scheduler_thread
    
    with _scheduler_lock:
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _scheduler_thread = threading.Thread(
                target=run_scheduled_task,
                daemon=True,  # Thread dies when main app dies
                name="MySchedulerThread"
            )
    
    return _scheduler_thread
```

### Integration in app.py

Add initialisation function and call it at module level:

```python
def init_my_scheduler():
    """Initialise and start the scheduler."""
    try:
        from my_scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.start()
        logger.info("My scheduler initialisation attempted")
    except Exception as e:
        logger.error(f"Failed to initialise scheduler: {str(e)}")

# Start scheduler when module is loaded (at end of app.py)
init_my_scheduler()
```

### Why Daemon Threads?
- **Automatic Cleanup**: Daemon threads terminate when the main app stops
- **Single Container**: No need for multiple containers or services
- **Simpler Deployment**: Everything runs in the Flask app container
- **Shared Context**: Direct access to Flask app, database, and models

### Testing Background Services
- Test via API endpoints (create conditions, verify results via API)
- Test lock file behaviour (ensure it prevents concurrent execution)
- Test error recovery (simulate failures, verify continued operation)
- Test notification generation (if applicable)
- **Note**: Don't test actual timing/sleep in unit tests (too slow, unreliable)

## Utility Modules

For reusable logic shared across multiple features:

### When to Create a Utility Module
- Business logic used by both API endpoints and background services
- Complex calculations that need unit testing
- Algorithm implementations that don't depend on database models

### Structure
- Create `feature_utils.py` in server directory
- Pure functions with clear inputs/outputs
- Comprehensive docstrings with examples
- Type hints for all parameters and returns

### Example

```python
def calculate_next_occurrence(start_time: datetime, interval: int, unit: str) -> datetime:
    """Calculate next occurrence of a scheduled event.
    
    Args:
        start_time: When to start calculating from
        interval: How many units between occurrences
        unit: Time unit (minute, hour, day, week, month, year)
    
    Returns:
        datetime: Next occurrence time
    
    Example:
        >>> calculate_next_occurrence(
        ...     datetime(2025, 1, 15),
        ...     2,
        ...     'week'
        ... )
        datetime(2025, 1, 29, 0, 0)
    """
    # Implementation
```

### Testing Utility Modules
- Create `test_feature_utils.py` with unit tests
- Test edge cases (boundaries, invalid input)
- Test with realistic data
- Mock time-dependent functions if needed

## Testing Requirements

All code contributions must include appropriate tests. See [TESTING.md](docs/TESTING.md) for comprehensive testing guidelines.

### Test Coverage Requirements

- **New Features**: Must include tests for all new functionality
- **Bug Fixes**: Must include a test that fails before the fix and passes after

### Required Test Categories

1. **Happy Path**: Test successful operations with valid input
2. **Error Cases**: Test error handling and validation
3. **Edge Cases**: Test boundary conditions
4. **Security**: Test input validation, path traversal prevention, etc.

### Example Test Structure

```python
@pytest.mark.api
class TestNewFeatureAPI:
    """Test cases for new feature."""
    
    def test_feature_success(self, api_client):
        """Test successful operation."""
        response = requests.post(
            f'{api_client}/api/new-feature',
            json={"data": "test"}
        )
        assert response.status_code == 200
        assert response.json()['success'] is True
    
    def test_feature_invalid_input(self, api_client):
        """Test operation with invalid input."""
        response = requests.post(
            f'{api_client}/api/new-feature',
            json={"data": ""}
        )
        assert response.status_code == 400
        assert response.json()['success'] is False
```

### Running Tests Before PR

```bash
# Run all backend tests
pytest -v

# Check coverage
pytest --cov=. --cov-report=term-missing

# Run only your new tests
pytest tests/test_your_feature.py -v
```

```bash
# Run UI/E2E tests (if your change touches www/)
cd ui-tests
pytest -v
```

## UI/E2E Testing Requirements

Changes that touch `www/` (HTML/CSS/JS) must include a Playwright UI test
covering the change, in addition to any backend API tests. See
[UI_TESTING.md](ui-tests/docs/UI_TESTING.md) for setup, conventions, and the
`logged_in_page` fixture.

```bash
cd ui-tests
pytest -v
```

UI tests interact with the app the same way a user would (clicking,
filling forms, asserting on visible DOM), never by reaching into the
database or importing frontend JS directly - the same API-only-equivalent
discipline as the backend suite, applied to the browser.

## Accessibility Requirements

All UI changes must meet accessibility standards. See [ACCESSIBILITY.md](docs/ACCESSIBILITY.md) for comprehensive guidelines.

### Required for All UI Changes

- ✅ **Semantic HTML**: Use appropriate HTML5 elements
- ✅ **ARIA Attributes**: Add proper ARIA labels and roles
- ✅ **Keyboard Navigation**: All interactive elements must be keyboard accessible
- ✅ **Focus Management**: Visible focus indicators and logical tab order
- ✅ **Color Contrast**: Meet WCAG AA standards (4.5:1 for normal text)
- ✅ **Screen Reader Testing**: Test with NVDA, JAWS, or VoiceOver

### Modal Dialogs Must Include

```html
<div id="myModal" class="modal" 
     role="dialog" 
     aria-modal="true" 
     aria-labelledby="modal-title" 
     aria-describedby="modal-description">
  <div class="modal-content">
    <h2 id="modal-title">Modal Title</h2>
    <p id="modal-description">Modal description</p>
  </div>
</div>
```

### Modal Styling Standards

- Reuse existing modal classes and layout patterns before creating new modal-specific variants.
- Keep modal content spacing consistent with existing UI spacing conventions (header/body/action areas should not be flush to edges).
- Use CSS variables for modal colors and states (normal, hover, focus, disabled) to preserve theme support.
- Reserve danger/error styling only for destructive actions (for example delete/confirm-destructive flows).

### Forms Must Include

- Proper `<label>` elements associated with inputs
- Error messages linked with `aria-describedby`
- Required fields marked with `aria-required="true"`

### Testing Accessibility

1. Use browser DevTools accessibility inspector
2. Test keyboard navigation (Tab, Enter, Escape, Arrow keys)
3. Test with a screen reader
4. Run automated tools (axe DevTools, Lighthouse)

## Frontend Error Handling

All frontend API interactions must follow error handling best practices to ensure a consistent user experience when the database or API is unavailable.

See [FRONTEND_ERROR_HANDLING.md](docs/FRONTEND_ERROR_HANDLING.md) for comprehensive guidelines on:

- **Database Connection Monitoring**: Continuous polling and status tracking
- **API Call Patterns**: 5-second timeouts with AbortController
- **Visual Feedback**: Loading states, toast notifications, loading overlays
- **State Preservation**: Keep modals open on failure, rollback UI changes
- **Error Notifications**: Non-blocking toasts instead of blocking alerts
- **Testing Guidelines**: Manual and automated testing requirements

### Quick Reference

All API calls must:
1. Use AbortController with 5-second timeout
2. Show loading state (with 500ms delay to avoid flashing)
3. Display non-blocking toast on error (never use `alert()`)
4. Preserve user work on failure (keep modals open)
5. Rollback UI changes for optimistic updates
6. Check database connection before opening modals

## Security Guidelines

All code must follow security best practices. See [server/docs/SECURITY.md](server/docs/SECURITY.md) for comprehensive security guidelines.

### Required Security Practices

1. **Input Validation**: Validate all user input
   - Type checking
   - Length limits
   - Format validation
   - Sanitisation

2. **SQL Injection Prevention**: Use parameterized queries
   ```python
   # Good - Parameterized query
   db.query(Board).filter(Board.id == board_id)
   
   # Bad - String concatenation
   db.execute(f"SELECT * FROM boards WHERE id = {board_id}")
   ```

3. **XSS Prevention**: Escape output in frontend
   ```javascript
   // Good - Use textContent or framework escaping
   element.textContent = userInput;
   
   // Bad - Direct HTML injection
   element.innerHTML = userInput;
   ```

4. **Path Traversal Prevention**: Validate filenames
   ```python
   # Validate filename format
   if not re.match(r'^[a-zA-Z0-9_-]+\.[a-z]+$', filename):
       return error("Invalid filename")
   ```

5. **Error Handling**: Don't expose internal details
   ```python
   try:
       # Operation
   except Exception as e:
       logger.error(f"Internal error: {str(e)}")
       return jsonify({"success": False, "message": "Operation failed"}), 500
   ```

### Security Testing Requirements

- Test with invalid/malicious input
- Test path traversal attempts
- Test SQL injection attempts
- Test XSS payloads
- Verify error messages don't leak sensitive data

## Pull Request Process

### Before Submitting

- [ ] Code follows project style guidelines
- [ ] All tests pass (`pytest -v`)
- [ ] New tests added for new functionality
- [ ] Test coverage is maintained or improved
- [ ] Accessibility requirements met (for UI changes)
- [ ] Security guidelines followed
- [ ] Documentation updated (if needed)
- [ ] Commit messages follow conventions
- [ ] Branch is up to date with main

### PR Template

When creating a PR, include:

```markdown
## Description
Brief description of the changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All existing tests pass
- [ ] New tests added
- [ ] Manual testing completed

## Accessibility
- [ ] Keyboard navigation tested
- [ ] Screen reader compatible
- [ ] ARIA attributes added (if applicable)

## Security
- [ ] Input validation added
- [ ] No sensitive data exposed
- [ ] Security tests added (if applicable)

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] Accessibility verified
- [ ] Security reviewed
```

### Review Process

1. **Automated Checks**: CI/CD runs tests automatically
2. **Code Review**: Maintainer reviews code
3. **Feedback**: Address any requested changes
4. **Approval**: PR is approved by maintainer
5. **Merge**: PR is merged into main branch

### After Merge

- Delete your branch: `git branch -d feature/your-feature-name`
- Pull the latest: `git pull upstream main`

## Style Guide

### Python

```python
# Good
def create_backup(filename: str, config: dict) -> dict:
    """Create a database backup.
    
    Args:
        filename: Name for the backup file
        config: Backup configuration dictionary
    
    Returns:
        Dictionary with success status and filename
    """
    if not filename:
        raise ValueError("Filename is required")
    
    # Implementation
    return {"success": True, "filename": filename}


# Bad
def create_backup(filename,config):
    if not filename:raise ValueError("Filename is required")
    return {"success":True,"filename":filename}
```

### JavaScript

```javascript
// Good
class BackupManager {
  constructor() {
    this.backups = [];
  }

  async createBackup(filename) {
    if (!filename) {
      throw new Error('Filename is required');
    }
    
    const response = await fetch('/api/backup', {
      method: 'POST',
      body: JSON.stringify({ filename })
    });
    
    return response.json();
  }
}

// Bad
class BackupManager{
  constructor(){this.backups=[]}
  async createBackup(filename){
    if(!filename)throw new Error('Filename is required')
    const response=await fetch('/api/backup',{method:'POST',body:JSON.stringify({filename})})
    return response.json()
  }
}
```

### HTML

```html
<!-- Good -->
<form id="backupForm" aria-label="Backup settings">
  <div class="form-group">
    <label for="backupName">Backup Name</label>
    <input 
      type="text" 
      id="backupName" 
      name="backup_name" 
      required
      aria-required="true"
      aria-describedby="name-help"
    >
    <p id="name-help" class="help-text">
      Enter a name for your backup
    </p>
  </div>
  <button type="submit" class="btn btn-primary">
    Create Backup
  </button>
</form>

<!-- Bad -->
<form>
  <div>
    <span>Backup Name</span>
    <input type="text">
    <span>Enter a name for your backup</span>
  </div>
  <div onclick="submitForm()">Create Backup</div>
</form>
```

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, missing semicolons, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples

```bash
# Feature
git commit -m "feat(backup): add manual backup functionality"

# Bug fix
git commit -m "fix(api): prevent path traversal in backup endpoints"

# Documentation
git commit -m "docs: add accessibility guidelines"

# Multiple lines
git commit -m "feat(backup): add restore from auto backups

- Add API endpoint for listing backups
- Add UI for selecting and restoring backups
- Add modal confirmation dialog
- Add comprehensive tests"

# Breaking change
git commit -m "feat(api): change backup API response format

BREAKING CHANGE: Backup API now returns 'backups' array instead of 'files'"
```

### Scope (Optional)

- `api`: API changes
- `ui`: UI changes
- `backup`: Backup-related changes
- `auth`: Authentication changes
- `db`: Database changes
- `test`: Test changes
- `docs`: Documentation changes

## Questions or Need Help?

- **Issues**: Open an issue for bugs or feature requests
- **Discussions**: Use GitHub Discussions for questions
- **Pull Requests**: Open a draft PR if you want early feedback

## Recognition

Contributors are recognised in:
- GitHub contributors page
- Release notes (for significant contributions)

Thank you for contributing to AFT!

---

**Last Updated**: 2025-11-30

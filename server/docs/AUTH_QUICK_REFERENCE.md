# Authentication & Authorization Quick Reference

## Essential Imports

```python
from flask import g, abort
from utils import (
    get_user_scoped_query,
    require_permission,
    require_board_access,
    require_authentication,
    get_current_user_id,
    can_access_board
)
from models import User, Board, Card
```

## Common Patterns

### 1. Get Current User

```python
# Get user ID
user_id = g.user.id

# Get full user object
user = g.user
```

### 2. Query User's Data

```python
# Boards owned by user
boards = get_user_scoped_query(db, Board, user_id).all()

# Specific board
board = get_user_scoped_query(db, Board, user_id).filter(
    Board.id == board_id
).first()

# Cards (automatically filters by board ownership)
cards = get_user_scoped_query(db, Card, user_id).filter(
    Card.column_id == column_id
).all()
```

### 3. Protect Endpoints

```python
# Require authentication only
@app.route('/api/profile')
@require_authentication
def get_profile():
    return jsonify({'user': g.user.display_name})

# Require specific permission
@app.route('/api/boards', methods=['POST'])
@require_permission('board.create')
def create_board():
    # User has 'board.create' permission
    pass

# Require board access
@app.route('/api/boards/<int:board_id>')
@require_board_access()
def get_board(board_id):
    # User can access this board
    pass

# Require board ownership
@app.route('/api/boards/<int:board_id>', methods=['DELETE'])
@require_board_access(require_owner=True)
def delete_board(board_id):
    # User owns this board
    pass

# Combine multiple decorators
@app.route('/api/boards/<int:board_id>/cards', methods=['POST'])
@require_board_access()
@require_permission('card.create')
def create_card(board_id):
    # User can access board AND has card.create permission
    pass
```

### 4. Create Resources

```python
# Always set owner/creator to current user
user_id = g.user.id

board = Board(
    name=data['name'],
    owner_id=user_id  # REQUIRED
)

card = Card(
    title=data['title'],
    column_id=column_id,
    created_by_id=user_id,  # Track creator
    assigned_to_id=data.get('assigned_to')  # Optional
)
```

### 5. Manual Permission Check

```python
from utils import get_user_permissions
from permissions import has_permission

# Get all user permissions
perms = get_user_permissions(user_id)

# Check specific permission
if has_permission(perms, 'board.delete'):
    # User can delete boards
    pass

# Get board-specific permissions
board_perms = get_user_permissions(user_id, board_id=board_id)
```

### 6. Check Board Access

```python
# Check if user can access board
has_access, is_owner = can_access_board(user_id, board_id)

if not has_access:
    abort(403, description="Access denied")

if is_owner:
    # User owns the board
    pass
```

## Default Users & Roles

After migration:

### Admin User
- **Username**: `admin`
- **Email**: `admin@localhost`
- **Role**: `administrator` (global)
- **Permissions**: All permissions

### Available Roles
- `administrator` - Full system access
- `board_admin` - Full board management
- `editor` - Create/edit cards
- `read_only` - View only

## Permission List

### System
- `system.admin` - Full system administration
- `user.manage` - Manage users
- `role.manage` - Manage roles
- `global_board.manage` - Rename global boards and set how long done cards show

### Boards
- `board.create` - Create boards
- `board.view` - View boards
- `board.edit` - Edit board details
- `board.delete` - Delete boards

### Cards
- `card.create` - Create cards
- `card.view` - View cards
- `card.edit` - Edit cards
- `card.delete` - Delete cards
- `card.archive` - Archive cards

### Other
- `schedule.*` - Schedule management
- `settings.*` - Settings access
- `backup.*` - Backup operations
- `theme.*` - Theme management

## Security Checklist

✅ Use `get_user_scoped_query()` for all data queries
✅ Get user_id from `g.user.id`, never from request
✅ Apply permission decorators to endpoints
✅ Set `owner_id`/`created_by_id` when creating resources
✅ Return 403 for access denied, 404 for not found
✅ Use `require_board_access()` for board operations
✅ Test cross-user access attempts

## Common Mistakes to Avoid

❌ `db.query(Board).all()` - Accesses all boards (insecure)
✅ `get_user_scoped_query(db, Board, user_id).all()` - Only user's boards

❌ `user_id = request.json['user_id']` - Client can lie
✅ `user_id = g.user.id` - From authenticated session

❌ No permission check on endpoint
✅ `@require_permission('board.edit')` - Enforces permission

❌ Forgetting to set owner_id when creating
✅ `board = Board(name='...', owner_id=g.user.id)` - Always set

## Testing Helpers

```python
from auth_helpers import (
    create_user,
    assign_role_to_user,
    show_user_permissions,
    list_all_roles
)

# Create test user
user = create_user('test@example.com', 'testuser')

# Assign role
assign_role_to_user(user.id, 'editor')

# View permissions
show_user_permissions(user.id)

# List all roles
list_all_roles()
```

## Migration Commands

```bash
# Run migrations
cd server
python migrate.py upgrade

# Or with alembic
alembic upgrade head

# Check current version
alembic current

# Rollback one migration
alembic downgrade -1
```

## Next Steps

1. Run migrations to create tables
2. Implement authentication middleware (JWT/sessions)
3. Update API endpoints to use decorators
4. Add login/logout endpoints
5. Implement OAuth providers (optional)
6. Update frontend to handle authentication

See [AUTHENTICATION.md](AUTHENTICATION.md) for detailed implementation guide.

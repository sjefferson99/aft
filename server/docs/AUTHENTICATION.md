# Authentication and Authorization Implementation Guide

## Overview

This document describes the multi-tenant authentication and authorisation system implemented in AFT. The system provides:

- **User management** with support for local authentication and OAuth providers
- **Role-Based Access Control (RBAC)** with flexible permission system
- **Row-Level Security (RLS)** ensuring data isolation between users
- **Secure-by-default API patterns** that prevent accidental data leaks

## Architecture

### Database Schema

#### New Tables

1. **users** - User accounts
   - Primary authentication/identity table
   - Supports both local auth (password_hash) and OAuth (oauth_provider, oauth_sub)
   - Tracks account status (is_active, email_verified)

2. **roles** - Permission groups
   - Defines sets of permissions as JSON arrays
   - System roles (is_system_role=true) cannot be deleted by users
   - Initial roles: administrator, board_admin, editor, read_only

3. **user_roles** - Role assignments
   - Many-to-many relationship between users and roles
   - Supports board-level role scoping (board_id)
   - Global roles when board_id is NULL

#### Updated Tables

All existing tables have been updated for multi-tenancy:

- **boards**: Added `owner_id` (required) - Board owner has full control
- **cards**: Added `created_by_id`, `assigned_to_id` (optional) - Track creator and assignee
- **settings**: Added `user_id` (optional) - NULL = global setting, otherwise user-specific
- **themes**: Added `user_id` (optional) - NULL = system theme, otherwise user's custom theme
- **notifications**: Added `user_id` (required) - Notifications belong to specific users

### Permission System

Permissions are granular strings in the format `resource.action`:

- **System**: `system.admin`, `user.manage`, `role.manage`
- **Boards**: `board.create`, `board.view`, `board.edit`, `board.delete`
- **Cards**: `card.create`, `card.view`, `card.edit`, `card.delete`, `card.archive`
- **Schedules**: `schedule.create`, `schedule.edit`, `schedule.delete`
- **Settings**: `setting.view`, `setting.edit`
- **Themes**: `theme.create`, `theme.edit`, `theme.delete`

See `permissions.py` for the complete list.

## Security Patterns

### 1. Secure Query Scoping

**CRITICAL**: Always use `get_user_scoped_query()` when querying user-owned data.

```python
from utils import get_user_scoped_query, get_current_user_id
from models import Board

# CORRECT: Automatically scoped to user
user_id = get_current_user_id()
boards = get_user_scoped_query(db, Board, user_id).all()

# WRONG: Can access other users' data
boards = db.query(Board).all()  # DON'T DO THIS!
```

The `get_user_scoped_query()` function:
- Automatically adds WHERE clauses to filter by user_id/owner_id
- Handles hierarchical permissions (e.g., Cards inherit from Boards)
- **Fails secure**: Returns empty results or raises error if scoping is undefined

### 2. Permission Checking

Use decorators to enforce permissions at the API level:

```python
from utils import require_permission, require_board_access, require_authentication

# Require specific permission
@app.route('/api/boards', methods=['POST'])
@require_permission('board.create')
def create_board():
    # User is guaranteed to have 'board.create' permission
    pass

# Require board access
@app.route('/api/boards/<int:board_id>', methods=['GET'])
@require_board_access()  # User must have access to the board
def get_board(board_id):
    # User is guaranteed to have access to this board
    pass

# Require board ownership
@app.route('/api/boards/<int:board_id>', methods=['DELETE'])
@require_board_access(require_owner=True)  # User must be the owner
def delete_board(board_id):
    # User is guaranteed to be the board owner
    pass

# Just require authentication
@app.route('/api/profile', methods=['GET'])
@require_authentication
def get_profile():
    # User is logged in, g.user is available
    pass
```

### 3. Never Trust Client Input

**Always get user_id from the session/token, never from request body:**

```python
# CORRECT
user_id = g.user.id  # From authenticated session

# WRONG
user_id = request.json.get('user_id')  # Client can lie!
```

### 4. Hierarchical Access Control

Access to child resources is inherited from parent:
- **Board owner** → can access all Columns, Cards, ChecklistItems, Comments, ScheduledCards
- **Card creator** → tracked but doesn't override board ownership
- **Card assignee** → tracked for organisation but doesn't grant special access

### 5. Board Sharing (Future)

The schema supports board sharing:
- Add UserRole entries with board_id set to specific board
- Example: Assign 'editor' role to User 5 on Board 10
- User can then access that board even if they don't own it

## API Implementation Patterns

### Creating Resources

```python
@app.route('/api/boards', methods=['POST'])
@require_permission('board.create')
def create_board():
    user_id = g.user.id
    data = request.get_json()
    
    board = Board(
        name=data['name'],
        description=data.get('description'),
        owner_id=user_id  # ALWAYS set owner to current user
    )
    
    db.add(board)
    db.commit()
    
    return jsonify({'id': board.id}), 201
```

### Reading Resources

```python
@app.route('/api/boards/<int:board_id>', methods=['GET'])
@require_board_access()
def get_board(board_id):
    user_id = g.user.id
    db = SessionLocal()
    
    # Use scoped query
    board = get_user_scoped_query(db, Board, user_id).filter(
        Board.id == board_id
    ).first()
    
    if not board:
        abort(404, description="Board not found")
    
    return jsonify(board.to_dict())
```

### Updating Resources

```python
@app.route('/api/boards/<int:board_id>', methods=['PATCH'])
@require_board_access()
@require_permission('board.edit')
def update_board(board_id):
    user_id = g.user.id
    data = request.get_json()
    db = SessionLocal()
    
    # Use scoped query to ensure user owns this board
    board = get_user_scoped_query(db, Board, user_id).filter(
        Board.id == board_id
    ).first()
    
    if not board:
        abort(404, description="Board not found")
    
    # Update fields
    if 'name' in data:
        board.name = data['name']
    
    board.updated_at = func.now()
    db.commit()
    
    return jsonify({'success': True})
```

### Deleting Resources

```python
@app.route('/api/boards/<int:board_id>', methods=['DELETE'])
@require_board_access(require_owner=True)
@require_permission('board.delete')
def delete_board(board_id):
    user_id = g.user.id
    db = SessionLocal()
    
    # Use scoped query
    board = get_user_scoped_query(db, Board, user_id).filter(
        Board.id == board_id
    ).first()
    
    if not board:
        abort(404, description="Board not found")
    
    db.delete(board)
    db.commit()
    
    return jsonify({'success': True})
```

## Migration Process

### Running Migrations

```bash
cd server

# Run the migrations
python migrate.py upgrade

# Or with Alembic directly
alembic upgrade head
```

### What the Migrations Do

**Migration 020**: Creates new tables
- Creates users, roles, user_roles tables
- Inserts initial system roles
- Creates default admin user (username: 'admin', email: 'admin@localhost')
- Assigns administrator role to admin user

**Migration 021**: Updates existing tables
- Adds user_id/owner_id columns to existing tables (as nullable)
- Backfills existing data with admin user ID
- Makes required columns NOT NULL
- Adds foreign key constraints and indexes
- Updates unique constraints for multi-tenant support

### Default Admin User

After migration, you'll have:
- **Username**: admin
- **Email**: admin@localhost
- **Role**: administrator (full system access)
- **Password**: Not set - implement password reset or OAuth login

## Authentication Implementation (Future)

The schema is ready for authentication. You'll need to implement:

### 1. Session/JWT Middleware

```python
from flask import g
from models import User

@app.before_request
def load_user_from_session():
    """Load user from session/JWT token into Flask g object."""
    user_id = session.get('user_id')  # or decode from JWT
    
    if user_id:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        db.close()
        
        if user and user.is_active:
            g.user = user
        else:
            g.user = None
    else:
        g.user = None
```

### 2. Login Endpoint

```python
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    # Verify credentials
    user = authenticate_user(email, password)
    
    if user:
        # Create session or JWT
        session['user_id'] = user.id
        user.last_login_at = func.now()
        db.commit()
        
        return jsonify({'success': True, 'user': user.to_dict()})
    
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
```

### 3. OAuth Integration

```python
from authlib.integrations.flask_client import OAuth

oauth = OAuth(app)

# Register OAuth providers
google = oauth.register(
    name='google',
    client_id='YOUR_CLIENT_ID',
    client_secret='YOUR_CLIENT_SECRET',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

@app.route('/api/auth/google')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/api/auth/google/callback')
def google_callback():
    token = google.authorize_access_token()
    user_info = token['userinfo']
    
    # Find or create user
    user = User.query.filter_by(
        oauth_provider='google',
        oauth_sub=user_info['sub']
    ).first()
    
    if not user:
        user = User(
            email=user_info['email'],
            display_name=user_info['name'],
            oauth_provider='google',
            oauth_sub=user_info['sub'],
            email_verified=True,
            is_active=True
        )
        db.add(user)
        
        # Assign default role
        assign_role_to_user(user.id, 'editor')
        db.commit()
    
    # Create session
    session['user_id'] = user.id
    user.last_login_at = func.now()
    db.commit()
    
    return redirect('/')
```

## Testing

### Unit Testing Permissions

```python
def test_user_permissions():
    """Test that users have correct permissions."""
    from utils import get_user_permissions
    
    # Admin should have all permissions
    admin_perms = get_user_permissions(1)
    assert 'system.admin' in admin_perms
    assert 'board.delete' in admin_perms
    
    # Editor should not have admin permissions
    editor_perms = get_user_permissions(2)
    assert 'system.admin' not in editor_perms
    assert 'board.view' in editor_perms
    assert 'card.edit' in editor_perms
```

### Testing Query Scoping

```python
def test_query_scoping_prevents_cross_user_access():
    """Test that users can't access other users' data."""
    from utils import get_user_scoped_query
    from models import Board
    
    # User 1 creates a board
    board1 = Board(name="User 1 Board", owner_id=1)
    db.add(board1)
    db.commit()
    
    # User 2 creates a board
    board2 = Board(name="User 2 Board", owner_id=2)
    db.add(board2)
    db.commit()
    
    # User 1 should only see their board
    user1_boards = get_user_scoped_query(db, Board, 1).all()
    assert len(user1_boards) == 1
    assert user1_boards[0].id == board1.id
    
    # User 2 should only see their board
    user2_boards = get_user_scoped_query(db, Board, 2).all()
    assert len(user2_boards) == 1
    assert user2_boards[0].id == board2.id
```

## Best Practices

1. **Always use scoped queries** - Use `get_user_scoped_query()` for all user data access
2. **Never trust client input** - Get user_id from authenticated session
3. **Use permission decorators** - Apply `@require_permission()` to all endpoints
4. **Fail secure** - Return 403/404 rather than exposing whether resource exists
5. **Audit trail** - Use `created_by_id` to track who created resources
6. **Test boundaries** - Write tests that attempt cross-user access
7. **Index foreign keys** - All user_id/owner_id columns are indexed for performance

## Helper Scripts

Use `auth_helpers.py` for common operations:

```python
from auth_helpers import create_user, assign_role_to_user, show_user_permissions

# Create a new user
user = create_user('newuser@example.com', 'newuser', 'New User')

# Assign a role
assign_role_to_user(user.id, 'editor')

# Show their permissions
show_user_permissions(user.id)
```

## Future Enhancements

- **Team/Organisation support**: Add an organisations table with team members
- **Custom roles**: Allow admins to create custom roles with specific permissions
- **Audit logging**: Track all data access and modifications
- **API keys**: Generate API keys for programmatic access
- **Rate limiting**: Per-user rate limits for general API endpoints (password checks and sign-in are already limited, see `auth_rate_limit.py`)
- **Two-factor authentication**: Add 2FA support for enhanced security

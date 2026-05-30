"""
Helper script to demonstrate how to use the new authentication and authorization system.

This file provides examples and helper functions for:
- Creating users
- Assigning roles
- Checking permissions
- Using secure query scoping
"""

from database import SessionLocal
from models import User, Role, UserRole, Board, Card, Setting
from models import Theme
from theme_defaults import get_instance_default_theme_id
from utils import get_user_scoped_query, get_user_permissions, can_access_board
from permissions import INITIAL_ROLES, has_permission
from sqlalchemy.exc import IntegrityError
import json


# Default settings to be created for each new user
# Only includes settings from the User Settings page (settings.html)
DEFAULT_USER_SETTINGS = {
    "default_board": "null",  # JSON-encoded null
    "time_format": '"24"',  # JSON-encoded string
    "timezone": '"UTC"',  # JSON-encoded IANA timezone
    "working_style": '"kanban"',  # JSON-encoded string
    "selected_theme": "1",  # Fallback theme ID (resolved dynamically to Fresh Green)
}


def create_default_user_settings(user_id, db_session=None):
    """
    Create default settings for a new user.
    
    Args:
        user_id: User ID
        db_session: Optional database session to use (will create new one if not provided)
        
    Returns:
        Number of settings created
    """
    should_close = False
    if db_session is None:
        db_session = SessionLocal()
        should_close = True
    
    try:
        settings_created = 0
        # Resolve instance default theme; helper falls back to Fresh Green when unset/invalid.
        default_theme_id = str(get_instance_default_theme_id(db_session) or 1)

        resolved_settings = dict(DEFAULT_USER_SETTINGS)
        resolved_settings["selected_theme"] = default_theme_id

        for key, value in resolved_settings.items():
            # Check if setting already exists for this user
            existing = db_session.query(Setting).filter(
                Setting.user_id == user_id,
                Setting.key == key
            ).first()

            if existing:
                continue

            # Use a savepoint so duplicate-key races do not abort the outer transaction.
            try:
                with db_session.begin_nested():
                    setting = Setting(
                        key=key,
                        value=value,
                        user_id=user_id
                    )
                    db_session.add(setting)
                    db_session.flush()
                    settings_created += 1
            except IntegrityError:
                # Another request inserted the same setting concurrently.
                continue
        
        if should_close:
            db_session.commit()
        
        print(f"Created {settings_created} default settings for user {user_id}")
        return settings_created
    finally:
        if should_close:
            db_session.close()


def create_user(email, username=None, display_name=None, password_hash=None):
    """
    Create a new user.
    
    Args:
        email: User's email address (required, unique)
        username: Username (optional, unique if provided)
        display_name: Display name (optional)
        password_hash: Hashed password (optional, for local auth)
        
    Returns:
        User object
    """
    db = SessionLocal()
    try:
        user = User(
            email=email,
            username=username,
            display_name=display_name or username or email.split('@')[0],
            password_hash=password_hash,
            is_active=True,
            email_verified=False  # Set to True after email verification
        )
        db.add(user)
        db.flush()  # Get user ID
        
        # Create default settings for the new user
        create_default_user_settings(user.id, db)
        
        db.commit()
        db.refresh(user)
        print(f"Created user: {user.email} (ID: {user.id})")
        return user
    finally:
        db.close()


def assign_role_to_user(user_id, role_name, board_id=None):
    """
    Assign a role to a user.
    
    Args:
        user_id: User ID
        role_name: Name of the role (e.g., 'administrator', 'editor')
        board_id: Optional board ID to scope the role to a specific board
        
    Returns:
        UserRole object
    """
    db = SessionLocal()
    try:
        # Get the role
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        
        # Check if assignment already exists
        existing = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
            UserRole.board_id == board_id
        ).first()
        
        if existing:
            print(f"User {user_id} already has role '{role_name}'" + 
                  (f" on board {board_id}" if board_id else " (global)"))
            return existing
        
        # Create the assignment
        user_role = UserRole(
            user_id=user_id,
            role_id=role.id,
            board_id=board_id
        )
        db.add(user_role)
        db.commit()
        db.refresh(user_role)
        
        scope_msg = f" on board {board_id}" if board_id else " (global)"
        print(f"Assigned role '{role_name}' to user {user_id}{scope_msg}")
        return user_role
    finally:
        db.close()


def show_user_permissions(user_id, board_id=None):
    """
    Display all permissions for a user.
    
    Args:
        user_id: User ID
        board_id: Optional board ID to show board-specific permissions
    """
    permissions = get_user_permissions(user_id, board_id)
    
    scope_msg = f" on board {board_id}" if board_id else " (global)"
    print(f"\nPermissions for user {user_id}{scope_msg}:")
    
    if not permissions:
        print("  No permissions")
        return
    
    for perm in sorted(permissions):
        print(f"  - {perm}")
    
    print(f"\nTotal: {len(permissions)} permissions")


def demonstrate_secure_queries():
    """
    Demonstrate how to use secure query scoping.
    """
    db = SessionLocal()
    try:
        # Example: Get all boards for a user (automatically scoped)
        user_id = 1  # Admin user
        
        print("\n=== Demonstrating Secure Query Scoping ===\n")
        
        # Correct way: Use get_user_scoped_query
        boards = get_user_scoped_query(db, Board, user_id).all()
        print(f"Boards accessible to user {user_id}: {len(boards)}")
        for board in boards:
            print(f"  - {board.name} (ID: {board.id})")
        
        # Example: Get all cards for a user (automatically joins through columns and boards)
        cards = get_user_scoped_query(db, Card, user_id).all()
        print(f"\nCards accessible to user {user_id}: {len(cards)}")
        for card in cards[:5]:  # Show first 5
            print(f"  - {card.title} (ID: {card.id})")
        if len(cards) > 5:
            print(f"  ... and {len(cards) - 5} more")
            
    finally:
        db.close()


def create_test_users():
    """
    Create some test users with different roles for development.
    """
    print("\n=== Creating Test Users ===\n")
    
    db = SessionLocal()
    try:
        # Check if test users already exist
        if db.query(User).filter(User.email == 'editor@test.com').first():
            print("Test users already exist")
            return
        
        # Create editor user
        editor = create_user('editor@test.com', 'editor_user', 'Test Editor')
        assign_role_to_user(editor.id, 'editor')
        
        # Create read-only user
        readonly = create_user('readonly@test.com', 'readonly_user', 'Read Only User')
        assign_role_to_user(readonly.id, 'read_only')
        
        # Create board admin user
        board_admin = create_user('boardadmin@test.com', 'board_admin_user', 'Board Admin')
        assign_role_to_user(board_admin.id, 'board_admin')
        
        print("\nTest users created successfully!")
        print("You can now test with different permission levels.")
        
    finally:
        db.close()


def list_all_roles():
    """
    List all available roles and their permissions.
    """
    db = SessionLocal()
    try:
        print("\n=== Available Roles ===\n")
        
        roles = db.query(Role).all()
        for role in roles:
            perms = json.loads(role.permissions)
            print(f"{role.name}:")
            print(f"  Description: {role.description}")
            print(f"  System Role: {role.is_system_role}")
            print(f"  Permissions ({len(perms)}):")
            for perm in sorted(perms):
                print(f"    - {perm}")
            print()
            
    finally:
        db.close()


if __name__ == "__main__":
    """
    Run some example operations when script is executed directly.
    """
    print("=" * 70)
    print("AFT Authentication & Authorization System - Helper Script")
    print("=" * 70)
    
    # List all roles
    list_all_roles()
    
    # Show admin user permissions
    show_user_permissions(1)  # Admin user
    
    # Demonstrate secure queries
    demonstrate_secure_queries()
    
    # Optionally create test users (commented out by default)
    # create_test_users()
    
    print("\n" + "=" * 70)
    print("Done! You can import functions from this module in your code.")
    print("=" * 70)

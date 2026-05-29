"""Permission and role definitions for the application.

This module defines:
- Permission constants and role definitions
- Role scope validation (BOARD_SPECIFIC_ONLY_ROLES, GLOBAL_ONLY_ROLES)
- Permission model documentation via get_permission_model_info()

For complete permission model documentation, see get_permission_model_info() method
or access via API endpoint: GET /api/roles/permission-model
"""
import json

# Permission definitions - describes what each permission allows
PERMISSION_DEFINITIONS = {
    # Global admin permissions
    'system.admin': 'Full system administration',
    'monitoring.system': 'System monitoring and status checking',
    'admin.database': 'Database backup and restore operations',
    'branding.edit': 'Upload and manage instance branding (logo)',
    'user.manage': 'Manage all users',
    'user.role': 'Assign roles to users',
    'role.manage': 'Manage roles and permissions',
    
    # Board permissions
    'board.create': 'Create new boards',
    'board.view': 'View boards',
    'board.edit': 'Edit board details',
    'board.delete': 'Delete boards',
    
    # Card permissions
    'card.create': 'Create cards',
    'card.view': 'View cards',
    'card.edit': 'Edit cards',
    'card.update': 'Update card properties (title, description, status, etc.)',
    'card.delete': 'Delete cards',
    'card.archive': 'Archive/unarchive cards',
    
    # Column permissions
    'column.create': 'Create board columns',
    'column.update': 'Update column properties',
    'column.delete': 'Delete board columns',
    
    # Schedule permissions
    'schedule.create': 'Create scheduled cards',
    'schedule.view': 'View scheduled cards',
    'schedule.edit': 'Edit scheduled cards',
    'schedule.delete': 'Delete scheduled cards',
    
    # Settings permissions
    'setting.view': 'View settings',
    'setting.edit': 'Edit settings',
    
    # Theme permissions
    'theme.create': 'Create custom themes',
    'theme.view': 'View themes',
    'theme.edit': 'Edit own themes',
    'theme.delete': 'Delete own themes',
}

# Initial system roles with their permissions
INITIAL_ROLES = {
    # === GLOBAL ROLES (assigned without board_id) ===
    'administrator': {
        'description': '[GLOBAL] Full system administration - can see and manage everything',
        'is_system_role': True,
        'permissions': [
            # All permissions
            'system.admin',
            'monitoring.system',
            'admin.database',
            'branding.edit',
            'user.manage',
            'user.role',
            'role.manage',
            'board.create',
            'board.view',
            'board.edit',
            'board.delete',
            'card.create',
            'card.view',
            'card.edit',
            'card.update',
            'card.delete',
            'card.archive',
            'column.create',
            'column.update',
            'column.delete',
            'schedule.create',
            'schedule.view',
            'schedule.edit',
            'schedule.delete',
            'setting.view',
            'setting.edit',
            'theme.create',
            'theme.view',
            'theme.edit',
            'theme.delete',
        ]
    },
    'board_creator': {
        'description': '[GLOBAL] Can create new boards (and automatically owns them with full control)',
        'is_system_role': True,
        'permissions': [
            'board.create',
            'theme.create',
            'theme.view',
            'theme.edit',
            'theme.delete',
            'setting.view',
            'setting.edit',
        ]
    },
    'theme_user': {
        'description': '[GLOBAL] Full theme management for personal themes',
        'is_system_role': True,
        'permissions': [
            'theme.create',
            'theme.view',
            'theme.edit',
            'theme.delete',
            'setting.view',
            'setting.edit',
        ]
    },
    
    # === BOARD-SPECIFIC ROLES (assigned with board_id) ===
    # These roles GRANT ACCESS to the specific board
    'board_editor': {
        'description': '[BOARD-SPECIFIC] Full control of the assigned board - can manage everything on it',
        'is_system_role': True,
        'permissions': [
            'board.view',
            'board.edit',
            'board.delete',
            'card.create',
            'card.view',
            'card.edit',
            'card.update',
            'card.delete',
            'card.archive',
            'column.create',
            'column.update',
            'column.delete',
            'schedule.create',
            'schedule.view',
            'schedule.edit',
            'schedule.delete',
            'setting.view',
            'setting.edit',
            'theme.create',
            'theme.view',
            'theme.edit',
            'theme.delete',
        ]
    },
    'board_viewer': {
        'description': '[BOARD-SPECIFIC] Read-only access to the assigned board - cannot edit anything',
        'is_system_role': True,
        'permissions': [
            'board.view',
            'card.view',
            'schedule.view',
            'setting.view',
            'theme.view',
        ]
    }
}

# Roles that MUST be assigned to specific boards (cannot be global)
BOARD_SPECIFIC_ONLY_ROLES = {'board_editor', 'board_viewer'}

# Roles that MUST be global (cannot be board-specific)
GLOBAL_ONLY_ROLES = {'administrator', 'board_creator', 'theme_user'}


def get_role_permissions_json(role_name):
    """Get the permissions for a role as a JSON string."""
    if role_name in INITIAL_ROLES:
        return json.dumps(INITIAL_ROLES[role_name]['permissions'])
    return json.dumps([])


def validate_permission(permission):
    """Check if a permission string is valid."""
    return permission in PERMISSION_DEFINITIONS


def has_permission(user_permissions, required_permission):
    """
    Check if a user has a required permission.
    
    Args:
        user_permissions: Set or list of permission strings
        required_permission: Permission string to check
        
    Returns:
        bool: True if user has the permission or system.admin
    """
    # System admin has all permissions
    if 'system.admin' in user_permissions:
        return True
    
    return required_permission in user_permissions


def get_permission_model_info():
    """
    Get comprehensive information about the permission model.
    Returns documentation, role definitions, and examples for client consumption.
    
    Returns:
        dict: Permission model information including:
            - overview: High-level description
            - concepts: Key concepts (ownership, access, roles)
            - roles: List of all roles with descriptions and scope
            - examples: Usage examples
            - rules: Role assignment rules
    """
    return {
        'overview': {
            'title': 'Simplified Permission Model',
            'description': 'The permission system controls board access and user capabilities through ownership and role-based access control.'
        },
        'concepts': [
            {
                'title': 'Board Ownership',
                'points': [
                    'When you create a board, you OWN it',
                    'Board owners have full control over their boards automatically',
                    'Owners can view, edit, delete, and share their boards',
                    'No role assignment needed - ownership gives you everything'
                ]
            },
            {
                'title': 'Board Access for Non-Owners',
                'points': [
                    'Board access is granted through board-specific role assignments only',
                    'There is NO "global editor" or "global read only"',
                    'Non-owners must be explicitly granted a role on each board',
                    'Two board-specific roles: board_editor (full control) and board_viewer (read-only)'
                ]
            },
            {
                'title': 'Creating New Boards',
                'points': [
                    'Users need the board.create permission to create boards',
                    'Assign the board_creator role (global) to allow board creation',
                    'When they create a board, they automatically become the owner with full control'
                ]
            }
        ],
        'roles': {
            'global': [
                {
                    'name': 'administrator',
                    'description': 'Full system administration - can see and manage everything',
                    'scope': 'global',
                    'use_case': 'System management, can see ALL boards'
                },
                {
                    'name': 'board_creator',
                    'description': 'Can create new boards (and automatically owns them with full control)',
                    'scope': 'global',
                    'use_case': 'Regular users who should be able to create their own boards'
                },
                {
                    'name': 'theme_user',
                    'description': 'Can view system themes and fully manage their own copied themes',
                    'scope': 'global',
                    'use_case': 'Default role for all approved users to manage personal themes'
                }
            ],
            'board_specific': [
                {
                    'name': 'board_editor',
                    'description': 'Full control of the assigned board - can manage everything on it',
                    'scope': 'board-specific',
                    'use_case': 'Share full access to a specific board'
                },
                {
                    'name': 'board_viewer',
                    'description': 'Read-only access to the assigned board - cannot edit anything',
                    'scope': 'board-specific',
                    'use_case': 'Share read-only access to a specific board'
                }
            ]
        },
        'examples': [
            {
                'title': 'Regular User Who Creates Boards',
                'scenario': 'Alice has the board_creator role',
                'details': [
                    'Alice can create new boards',
                    'Board 1 (owned by Alice): Full control (automatic via ownership)',
                    'Board 2 (owned by Bob): No access unless Bob grants a board-specific role'
                ]
            },
            {
                'title': 'Sharing a Board',
                'scenario': 'Bob owns Board 2 and wants to share it with Alice',
                'details': [
                    'Option A: Grant Alice full control → Assign "board_editor" role to Alice on Board 2',
                    'Option B: Grant Alice read-only access → Assign "board_viewer" role to Alice on Board 2'
                ]
            },
            {
                'title': 'Different Access on Different Boards',
                'scenario': 'Charlie has different roles on different boards',
                'details': [
                    'Board 3 (owned by David): Assigned "board_viewer" → Can only view Board 3',
                    'Board 4 (owned by Eve): Assigned "board_editor" → Full control of Board 4'
                ]
            }
        ],
        'assignment_rules': [
            'Global roles (administrator, board_creator, theme_user) are assigned without selecting a board',
            'Board-specific roles (board_editor, board_viewer) MUST have a specific board selected',
            'Board owners can grant any role on their boards',
            'Users with user.role permission can grant roles they themselves have',
            'Administrators can grant any role'
        ],
        'summary': [
            'Core system roles include 3 global roles and 2 board-specific roles',
            'Board owners have full control, others need explicit access',
            'No confusing "global editor" that does not grant access',
            'Can share boards with fine-grained control'
        ]
    }

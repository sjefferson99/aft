"""
Role Management API endpoints.

This module provides:
- List all available roles
- Get role details and permissions
- Assign roles to users
- Remove roles from users
- Get user role assignments
"""

import logging
import json
from flask import Blueprint, request, g
from database import SessionLocal
from datetime_helpers import serialize_datetime
from models import User, Role, UserRole, Board
from utils import (
    create_error_response,
    create_success_response,
    require_permission,
    require_any_permission
)
from permissions import PERMISSION_DEFINITIONS

logger = logging.getLogger(__name__)

# Create blueprint for role management routes
role_mgmt_bp = Blueprint('role_management', __name__, url_prefix='/api/roles')


@role_mgmt_bp.route('', methods=['GET'])
@require_any_permission('role.manage', 'user.role')
def get_all_roles():
    """
    Get all available roles with their descriptions and permissions.
    ---
    tags:
      - Role Management
    responses:
      200:
        description: List of all roles
        schema:
          type: object
          properties:
            success:
              type: boolean
            roles:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  name:
                    type: string
                  description:
                    type: string
                  is_system_role:
                    type: boolean
                  permissions:
                    type: array
                    items:
                      type: string
                  created_at:
                    type: string
      403:
        description: Forbidden - requires role.manage or user.role permission
    """
    db = SessionLocal()
    try:
        roles = db.query(Role).order_by(Role.name).all()
        
        role_list = []
        for role in roles:
            permissions = json.loads(role.permissions) if isinstance(role.permissions, str) else role.permissions
            
            # Add metadata about role scope requirements
            from permissions import BOARD_SPECIFIC_ONLY_ROLES, GLOBAL_ONLY_ROLES
            role_data = {
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'is_system_role': role.is_system_role,
                'permissions': permissions,
                'created_at': serialize_datetime(role.created_at),
                'board_specific_only': role.name in BOARD_SPECIFIC_ONLY_ROLES,
                'global_only': role.name in GLOBAL_ONLY_ROLES
            }
            role_list.append(role_data)
        
        return create_success_response(data={'roles': role_list})
        
    finally:
        db.close()


@role_mgmt_bp.route('/permissions', methods=['GET'])
@require_any_permission('role.manage', 'user.role')
def get_all_permissions():
    """
    Get all available permissions with their descriptions.
    ---
    tags:
      - Role Management
    responses:
      200:
        description: List of all permissions
        schema:
          type: object
          properties:
            success:
              type: boolean
            permissions:
              type: object
              description: Object mapping permission names to descriptions
      403:
        description: Forbidden - requires role.manage or user.role permission
    """
    return create_success_response(data={'permissions': PERMISSION_DEFINITIONS})


@role_mgmt_bp.route('/permission-model', methods=['GET'])
def get_permission_model():
    """
    Get comprehensive information about the permission model.
    Returns documentation, role definitions, and examples for client-side display.
    No authentication required - this is public documentation.
    ---
    tags:
      - Role Management
    responses:
      200:
        description: Permission model information
        schema:
          type: object
          properties:
            success:
              type: boolean
            model:
              type: object
              description: Complete permission model documentation
              properties:
                overview:
                  type: object
                  properties:
                    title:
                      type: string
                    description:
                      type: string
                concepts:
                  type: array
                  items:
                    type: object
                    properties:
                      title:
                        type: string
                      points:
                        type: array
                        items:
                          type: string
                roles:
                  type: object
                  properties:
                    global:
                      type: array
                      items:
                        type: object
                    board_specific:
                      type: array
                      items:
                        type: object
                examples:
                  type: array
                  items:
                    type: object
                assignment_rules:
                  type: array
                  items:
                    type: string
                summary:
                  type: array
                  items:
                    type: string
    """
    from permissions import get_permission_model_info
    
    model_info = get_permission_model_info()
    return create_success_response(data={'model': model_info})


@role_mgmt_bp.route('/users', methods=['GET'])
@require_any_permission('role.manage', 'user.role')
def get_user_roles():
    """
    Get all active users with their role assignments.
    ---
    tags:
      - Role Management
    responses:
      200:
        description: List of users with their roles
        schema:
          type: object
          properties:
            success:
              type: boolean
            users:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  username:
                    type: string
                  email:
                    type: string
                  is_active:
                    type: boolean
                  roles:
                    type: array
                    items:
                      type: object
                      properties:
                        role_id:
                          type: integer
                        role_name:
                          type: string
                        board_id:
                          type: integer
                          nullable: true
                        board_name:
                          type: string
                          nullable: true
                        assigned_at:
                          type: string
      403:
        description: Forbidden - requires role.manage or user.role permission
    """
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active).order_by(User.username).all()
        
        user_list = []
        for user in users:
            # Get all role assignments for this user
            role_assignments = db.query(UserRole, Role, Board).join(
                Role, UserRole.role_id == Role.id
            ).outerjoin(
                Board, UserRole.board_id == Board.id
            ).filter(
                UserRole.user_id == user.id
            ).order_by(Role.name).all()
            
            roles = []
            for user_role, role, board in role_assignments:
                roles.append({
                    'role_id': role.id,
                    'role_name': role.name,
                    'board_id': board.id if board else None,
                    'board_name': board.name if board else None,
                    'assigned_at': serialize_datetime(user_role.created_at)
                })
            
            user_list.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_active': user.is_active,
                'roles': roles
            })
        
        return create_success_response(data={'users': user_list})
        
    finally:
        db.close()


@role_mgmt_bp.route('/assign', methods=['POST'])
@require_any_permission('role.manage', 'user.role')
def assign_role_to_user():
    """
    Assign a role to a user.
    ---
    tags:
      - Role Management
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - user_id
            - role_id
          properties:
            user_id:
              type: integer
              description: ID of the user
            role_id:
              type: integer
              description: ID of the role to assign
            board_id:
              type: integer
              description: Optional board ID for board-specific roles
    responses:
      200:
        description: Role assigned successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      400:
        description: Invalid request
      403:
        description: Forbidden - requires role.manage or user.role permission
      404:
        description: User or role not found
      409:
        description: Role already assigned
    """
    data = request.get_json()
    
    if not data or 'user_id' not in data or 'role_id' not in data:
        return create_error_response("user_id and role_id are required", 400)
    
    user_id = data['user_id']
    role_id = data['role_id']
    board_id = data.get('board_id')
    
    db = SessionLocal()
    try:
        # Check if user has role.manage permission (full access) or only user.role (restricted)
        from utils import get_user_permissions, get_user_role_ids
        from permissions import has_permission
        
        current_user_permissions = get_user_permissions(g.user.id)
        has_role_manage = has_permission(current_user_permissions, 'role.manage')
        
        # Prevent users from modifying their own roles
        if user_id == g.user.id:
            return create_error_response(
                "You cannot modify your own roles. Please ask another administrator for assistance.",
                403
            )
        
        # Verify user exists and is active
        user = db.query(User).filter(User.id == user_id, User.is_active).first()
        if not user:
            return create_error_response("User not found or inactive", 404)
        
        # Verify role exists
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            return create_error_response("Role not found", 404)
        
        # Validate role assignment scope (global vs board-specific)
        from permissions import BOARD_SPECIFIC_ONLY_ROLES, GLOBAL_ONLY_ROLES
        
        if role.name in BOARD_SPECIFIC_ONLY_ROLES and board_id is None:
            return create_error_response(
                f"Role '{role.name}' can only be assigned to specific boards. Please select a board.",
                400
            )
        
        if role.name in GLOBAL_ONLY_ROLES and board_id is not None:
            return create_error_response(
                f"Role '{role.name}' can only be assigned globally. Do not select a board.",
                400
            )
        
        # If user has only user.role permission (not role.manage), they can only assign roles they have
        if not has_role_manage:
            current_user_role_ids = get_user_role_ids(g.user.id, board_id)
            if role_id not in current_user_role_ids:
                return create_error_response(
                    f"You can only assign roles that you have been granted. You do not have the '{role.name}' role.",
                    403
                )
        
        # Verify board exists if board_id provided
        if board_id:
            board = db.query(Board).filter(Board.id == board_id).first()
            if not board:
                return create_error_response("Board not found", 404)
        
        # Check if role already assigned
        existing = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
            UserRole.board_id == board_id
        ).first()
        
        if existing:
            scope = f" on board {board_id}" if board_id else " (global)"
            return create_error_response(
                f"User already has role '{role.name}'{scope}",
                409
            )
        
        # Create new role assignment
        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
            board_id=board_id
        )
        db.add(user_role)
        db.commit()
        
        scope = f" on board {board_id}" if board_id else " (global)"
        logger.info(f"Role '{role.name}' assigned to user {user.email}{scope} by admin {g.user.id}")
        
        return create_success_response(
            message=f"Role '{role.name}' assigned to {user.username}"
        )
        
    finally:
        db.close()


@role_mgmt_bp.route('/remove', methods=['POST'])
@require_any_permission('role.manage', 'user.role')
def remove_role_from_user():
    """
    Remove a role from a user.
    ---
    tags:
      - Role Management
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - user_id
            - role_id
          properties:
            user_id:
              type: integer
              description: ID of the user
            role_id:
              type: integer
              description: ID of the role to remove
            board_id:
              type: integer
              description: Optional board ID for board-specific roles (must match the assignment)
    responses:
      200:
        description: Role removed successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      400:
        description: Invalid request
      403:
        description: Forbidden - requires role.manage or user.role permission
      404:
        description: User, role, or role assignment not found
    """
    data = request.get_json()
    
    if not data or 'user_id' not in data or 'role_id' not in data:
        return create_error_response("user_id and role_id are required", 400)
    
    user_id = data['user_id']
    role_id = data['role_id']
    board_id = data.get('board_id')
    
    db = SessionLocal()
    try:
        # Check if user has role.manage permission (full access) or only user.role (restricted)
        from utils import get_user_permissions, get_user_role_ids
        from permissions import has_permission
        
        current_user_permissions = get_user_permissions(g.user.id)
        has_role_manage = has_permission(current_user_permissions, 'role.manage')
        
        # Prevent users from modifying their own roles
        if user_id == g.user.id:
            return create_error_response(
                "You cannot modify your own roles. Please ask another administrator for assistance.",
                403
            )
        
        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return create_error_response("User not found", 404)
        
        # Verify role exists
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            return create_error_response("Role not found", 404)
        
        # If user has only user.role permission (not role.manage), they can only remove roles they have
        if not has_role_manage:
            current_user_role_ids = get_user_role_ids(g.user.id, board_id)
            if role_id not in current_user_role_ids:
                return create_error_response(
                    f"You can only remove roles that you have been granted. You do not have the '{role.name}' role.",
                    403
                )
        
        # Find the role assignment
        user_role = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
            UserRole.board_id == board_id
        ).first()
        
        if not user_role:
            scope = f" on board {board_id}" if board_id else " (global)"
            return create_error_response(
                f"User does not have role '{role.name}'{scope}",
                404
            )
        
        # Remove the role assignment
        db.delete(user_role)
        db.commit()
        
        scope = f" on board {board_id}" if board_id else " (global)"
        logger.info(f"Role '{role.name}' removed from user {user.email}{scope} by admin {g.user.id}")
        
        return create_success_response(
            message=f"Role '{role.name}' removed from {user.username}"
        )
        
    finally:
        db.close()


@role_mgmt_bp.route('/boards', methods=['GET'])
@require_any_permission('role.manage', 'user.role')
def get_boards_for_roles():
    """
    Get all boards for board-specific role assignments.
    ---
    tags:
      - Role Management
    responses:
      200:
        description: List of all boards
        schema:
          type: object
          properties:
            success:
              type: boolean
            boards:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  name:
                    type: string
      403:
        description: Forbidden - requires role.manage or user.role permission
    """
    db = SessionLocal()
    try:
        boards = db.query(Board).order_by(Board.name).all()
        
        board_list = []
        for board in boards:
            board_list.append({
                'id': board.id,
                'name': board.name
            })
        
        return create_success_response(data={'boards': board_list})
        
    finally:
        db.close()


@role_mgmt_bp.route('/my-roles', methods=['GET'])
@require_any_permission('role.manage', 'user.role')
def get_my_roles():
    """
    Get the current user's roles for filtering assignable roles.
    Returns all roles if user has role.manage, otherwise returns only their own roles.
    ---
    tags:
      - Role Management
    parameters:
      - name: board_id
        in: query
        type: integer
        description: Optional board ID to get board-specific roles
    responses:
      200:
        description: List of roles the current user can assign
        schema:
          type: object
          properties:
            success:
              type: boolean
            roles:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  name:
                    type: string
                  description:
                    type: string
            can_assign_all:
              type: boolean
              description: Whether user has role.manage (can assign any role)
      403:
        description: Forbidden - requires role.manage or user.role permission
    """
    from utils import get_user_permissions, get_user_role_ids
    from permissions import has_permission
    
    board_id = request.args.get('board_id', type=int)
    
    db = SessionLocal()
    try:
        current_user_permissions = get_user_permissions(g.user.id)
        has_role_manage = has_permission(current_user_permissions, 'role.manage')
        
        if has_role_manage:
            # User has role.manage - can assign any role
            roles = db.query(Role).order_by(Role.name).all()
            role_list = []
            from permissions import BOARD_SPECIFIC_ONLY_ROLES, GLOBAL_ONLY_ROLES
            for role in roles:
                role_list.append({
                    'id': role.id,
                    'name': role.name,
                    'description': role.description,
                    'board_specific_only': role.name in BOARD_SPECIFIC_ONLY_ROLES,
                    'global_only': role.name in GLOBAL_ONLY_ROLES
                })
            
            return create_success_response(data={
                'roles': role_list,
                'can_assign_all': True
            })
        else:
            # User has only user.role - can only assign roles they have
            # Get ALL roles the user has (global + any board-specific)
            if board_id is not None:
                # When assigning for a specific board, only show roles they have on that board
                current_user_role_ids = get_user_role_ids(g.user.id, board_id)
            else:
                # When viewing generally, show all global roles they have
                # (board-specific roles can only be used on those specific boards)
                current_user_role_ids = get_user_role_ids(g.user.id, None)
            
            if not current_user_role_ids:
                return create_success_response(data={
                    'roles': [],
                    'can_assign_all': False
                })
            
            roles = db.query(Role).filter(Role.id.in_(current_user_role_ids)).order_by(Role.name).all()
            role_list = []
            from permissions import BOARD_SPECIFIC_ONLY_ROLES, GLOBAL_ONLY_ROLES
            for role in roles:
                role_list.append({
                    'id': role.id,
                    'name': role.name,
                    'description': role.description,
                    'board_specific_only': role.name in BOARD_SPECIFIC_ONLY_ROLES,
                    'global_only': role.name in GLOBAL_ONLY_ROLES
                })
            
            return create_success_response(data={
                'roles': role_list,
                'can_assign_all': False
            })
        
    finally:
        db.close()


@role_mgmt_bp.route('', methods=['POST'])
@require_permission('role.manage')
def create_role():
    """
    Create a new role with permissions.
    ---
    tags:
      - Role Management
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - name
            - permissions
          properties:
            name:
              type: string
              description: Name of the role (max 50 characters)
            description:
              type: string
              description: Optional description of the role
            permissions:
              type: array
              description: Array of permission strings
              items:
                type: string
    responses:
      201:
        description: Role created successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            role:
              type: object
              properties:
                id:
                  type: integer
                name:
                  type: string
                description:
                  type: string
                permissions:
                  type: array
                  items:
                    type: string
      400:
        description: Invalid request
      403:
        description: Forbidden - requires role.manage permission
      409:
        description: Role name already exists
    """
    data = request.get_json()
    
    if not data or 'name' not in data or 'permissions' not in data:
        return create_error_response("name and permissions are required", 400)
    
    name = data['name'].strip()
    description = data.get('description', '').strip()
    permissions = data['permissions']
    
    # Validation
    if not name or len(name) > 50:
        return create_error_response("Role name must be between 1 and 50 characters", 400)
    
    if not isinstance(permissions, list):
        return create_error_response("Permissions must be an array", 400)
    
    # Validate permissions against known permissions
    for perm in permissions:
        if perm not in PERMISSION_DEFINITIONS:
            return create_error_response(f"Unknown permission: {perm}", 400)
    
    db = SessionLocal()
    try:
        # Check if role name already exists
        existing = db.query(Role).filter(Role.name == name).first()
        if existing:
            return create_error_response(f"Role '{name}' already exists", 409)
        
        # Create new role
        new_role = Role(
            name=name,
            description=description if description else None,
            is_system_role=False,  # User-created roles are never system roles
            permissions=json.dumps(permissions)
        )
        db.add(new_role)
        db.commit()
        db.refresh(new_role)
        
        logger.info(f"Role '{name}' created by admin {g.user.id}")
        
        return create_success_response(
            message=f"Role '{name}' created successfully",
            data={
                'role': {
                    'id': new_role.id,
                    'name': new_role.name,
                    'description': new_role.description,
                    'permissions': json.loads(new_role.permissions)
                }
            },
            status_code=201
        )
        
    finally:
        db.close()


@role_mgmt_bp.route('/<int:role_id>/copy', methods=['POST'])
@require_permission('role.manage')
def copy_role(role_id):
    """
    Create a copy of an existing role with a new name.
    ---
    tags:
      - Role Management
    parameters:
      - name: role_id
        in: path
        required: true
        type: integer
        description: ID of the role to copy
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
              description: Name for the copied role
    responses:
      201:
        description: Role copied successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            role:
              type: object
      400:
        description: Invalid request
      403:
        description: Forbidden - requires role.manage permission
      404:
        description: Role not found
      409:
        description: Role name already exists
    """
    data = request.get_json()
    
    if not data or 'name' not in data:
        return create_error_response("name is required", 400)
    
    new_name = data['name'].strip()
    
    if not new_name or len(new_name) > 50:
        return create_error_response("Role name must be between 1 and 50 characters", 400)
    
    db = SessionLocal()
    try:
        # Get the source role
        source_role = db.query(Role).filter(Role.id == role_id).first()
        if not source_role:
            return create_error_response("Source role not found", 404)
        
        # Check if new name already exists
        existing = db.query(Role).filter(Role.name == new_name).first()
        if existing:
            return create_error_response(f"Role '{new_name}' already exists", 409)
        
        # Create copy of the role
        new_role = Role(
            name=new_name,
            description=source_role.description,
            is_system_role=False,  # Copied roles are never system roles
            permissions=source_role.permissions  # Copy permissions as-is (JSON string)
        )
        db.add(new_role)
        db.commit()
        db.refresh(new_role)
        
        logger.info(f"Role '{source_role.name}' copied to '{new_name}' by admin {g.user.id}")
        
        permissions = json.loads(new_role.permissions) if isinstance(new_role.permissions, str) else new_role.permissions
        
        return create_success_response(
            message=f"Role '{new_name}' created as a copy of '{source_role.name}'",
            data={
                'role': {
                    'id': new_role.id,
                    'name': new_role.name,
                    'description': new_role.description,
                    'permissions': permissions
                }
            },
            status_code=201
        )
        
    finally:
        db.close()


@role_mgmt_bp.route('/<int:role_id>', methods=['DELETE'])
@require_permission('role.manage')
def delete_role(role_id):
    """
    Delete a role (cannot delete system roles).
    ---
    tags:
      - Role Management
    parameters:
      - name: role_id
        in: path
        required: true
        type: integer
        description: ID of the role to delete
    responses:
      200:
        description: Role deleted successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      400:
        description: Cannot delete system role
      403:
        description: Forbidden - requires role.manage permission
      404:
        description: Role not found
    """
    db = SessionLocal()
    try:
        # Get the role
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            return create_error_response("Role not found", 404)
        
        # Check if it's a system role
        if role.is_system_role:
            return create_error_response(
                "Cannot delete system role. System roles are protected.",
                400
            )
        
        role_name = role.name
        
        # Delete the role (cascade will handle UserRole assignments)
        db.delete(role)
        db.commit()
        
        logger.info(f"Role '{role_name}' (ID: {role_id}) deleted by admin {g.user.id}")
        
        return create_success_response(
            message=f"Role '{role_name}' deleted successfully"
        )
        
    finally:
        db.close()


@role_mgmt_bp.route('/<int:role_id>', methods=['PATCH'])
@require_permission('role.manage')
def update_role(role_id):
    """
    Update a role's details (name, description, or permissions).
    System roles cannot be modified.
    ---
    tags:
      - Role Management
    parameters:
      - name: role_id
        in: path
        required: true
        type: integer
        description: ID of the role to update
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              description: New name for the role
            description:
              type: string
              description: New description for the role
            permissions:
              type: array
              description: New array of permission strings
              items:
                type: string
    responses:
      200:
        description: Role updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            role:
              type: object
      400:
        description: Invalid request or cannot modify system role
      403:
        description: Forbidden - requires role.manage permission
      404:
        description: Role not found
      409:
        description: Role name already exists
    """
    data = request.get_json()
    
    if not data:
        return create_error_response("Request body is required", 400)
    
    db = SessionLocal()
    try:
        # Get the role
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            return create_error_response("Role not found", 404)
        
        # Check if it's a system role
        if role.is_system_role:
            return create_error_response(
                "Cannot modify system role. System roles are protected.",
                400
            )
        
        # Update name if provided
        if 'name' in data:
            new_name = data['name'].strip()
            if not new_name or len(new_name) > 50:
                return create_error_response("Role name must be between 1 and 50 characters", 400)
            
            # Check if new name conflicts with another role
            if new_name != role.name:
                existing = db.query(Role).filter(Role.name == new_name).first()
                if existing:
                    return create_error_response(f"Role '{new_name}' already exists", 409)
                role.name = new_name
        
        # Update description if provided
        if 'description' in data:
            role.description = data['description'].strip() if data['description'] else None
        
        # Update permissions if provided
        if 'permissions' in data:
            permissions = data['permissions']
            if not isinstance(permissions, list):
                return create_error_response("Permissions must be an array", 400)
            
            # Validate permissions
            for perm in permissions:
                if perm not in PERMISSION_DEFINITIONS:
                    return create_error_response(f"Unknown permission: {perm}", 400)
            
            role.permissions = json.dumps(permissions)
        
        db.commit()
        db.refresh(role)
        
        logger.info(f"Role '{role.name}' (ID: {role_id}) updated by admin {g.user.id}")
        
        permissions = json.loads(role.permissions) if isinstance(role.permissions, str) else role.permissions
        
        return create_success_response(
            message=f"Role '{role.name}' updated successfully",
            data={
                'role': {
                    'id': role.id,
                    'name': role.name,
                    'description': role.description,
                    'permissions': permissions,
                    'is_system_role': role.is_system_role
                }
            }
        )
        
    finally:
        db.close()


@role_mgmt_bp.route('/permission-mappings', methods=['GET'])
@require_any_permission('role.manage', 'user.role')
def get_permission_mappings():
    """
    Get dynamic mapping of permissions to API endpoints and vice versa.
    This endpoint analyzes the codebase at runtime to generate up-to-date mappings.
    ---
    tags:
      - Role Management
    responses:
      200:
        description: Mapping of permissions to endpoints and endpoints to permissions
      403:
        description: Forbidden - requires role.manage or user.role permission
    """
    import re
    from pathlib import Path
    from collections import defaultdict

    def extract_blueprint_prefixes(file_path):
        """Extract blueprint variable names and url prefixes from a Python file."""
        prefixes = {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return prefixes

        blueprint_pattern = re.compile(
            r"(\w+)\s*=\s*Blueprint\(\s*['\"][^'\"]+['\"]\s*,\s*__name__\s*(?:,\s*url_prefix\s*=\s*['\"]([^'\"]*)['\"])?"
        )

        for match in blueprint_pattern.finditer(content):
            blueprint_var = match.group(1)
            url_prefix = match.group(2) or ''
            prefixes[blueprint_var] = url_prefix

        return prefixes

    def extract_routes_from_file(file_path, blueprint_prefixes):
        """Extract routes and their decorators from a Python file."""
        routes = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return routes

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            route_match = re.search(r'@(\w+)\.route\([\'\"]([^\'\"]+)[\'\"](?:,\s*methods=\[([^\]]+)\])?\)', line)

            if route_match:
                route_owner = route_match.group(1)
                route_path = route_match.group(2)
                methods = route_match.group(3) if route_match.group(3) else '"GET"'
                methods = [m.strip().strip('"\'') for m in methods.split(',')]

                decorators = []
                j = i + 1
                while j < len(lines) and j < i + 10:
                    next_line = lines[j].strip()

                    perm_match = re.search(r'@require_permission\([\'\"]([^\'\"]+)[\'\"]\)', next_line)
                    if perm_match:
                        decorators.append({
                            'type': 'require_permission',
                            'permission': perm_match.group(1)
                        })

                    any_perm_match = re.search(r'@require_any_permission\(([^)]+)\)', next_line)
                    if any_perm_match:
                        perms_str = any_perm_match.group(1)
                        perms = [p.strip().strip('"\'') for p in perms_str.split(',')]
                        decorators.append({
                            'type': 'require_any_permission',
                            'permissions': perms
                        })

                    if '@require_authentication' in next_line:
                        decorators.append({'type': 'require_authentication'})

                    board_access_match = re.search(r'@require_board_access\(([^)]*)\)', next_line)
                    if board_access_match:
                        args = board_access_match.group(1)
                        decorators.append({
                            'type': 'require_board_access',
                            'require_owner': 'require_owner=True' in args
                        })

                    if next_line.startswith('def '):
                        break

                    j += 1

                if route_owner != 'app':
                    url_prefix = blueprint_prefixes.get(route_owner, '')
                    if url_prefix:
                        if route_path.startswith('/'):
                            route_path = f"{url_prefix.rstrip('/')}{route_path}"
                        else:
                            route_path = f"{url_prefix.rstrip('/')}/{route_path}"

                routes.append({
                    'path': route_path,
                    'methods': methods,
                    'decorators': decorators,
                    'file': file_path.name
                })

            i += 1

        return routes

    try:
        server_dir = Path(__file__).parent
        files_to_analyze = [
            file_path for file_path in server_dir.glob('*.py')
            if file_path.name not in {'database.py', 'models.py', 'permissions.py'}
            and not file_path.name.startswith('test_')
        ]

        blueprint_prefixes = {}
        for file_path in files_to_analyze:
            if file_path.exists():
                blueprint_prefixes.update(extract_blueprint_prefixes(file_path))

        all_routes = []
        for file_path in files_to_analyze:
            if file_path.exists():
                all_routes.extend(extract_routes_from_file(file_path, blueprint_prefixes))

        permission_to_endpoints = defaultdict(list)
        endpoint_to_permissions = {}

        for route in all_routes:
            endpoint_key = f"{route['path']}::{','.join(route['methods'])}"
            methods_str = ', '.join(route['methods'])

            has_permission = False
            permissions_list = []
            protection_type = 'public'

            for decorator in route['decorators']:
                if decorator['type'] == 'require_permission':
                    has_permission = True
                    perm = decorator['permission']
                    permissions_list.append(perm)
                    permission_to_endpoints[perm].append({
                        'path': route['path'],
                        'methods': route['methods']
                    })
                    protection_type = 'permission'
                elif decorator['type'] == 'require_any_permission':
                    has_permission = True
                    for perm in decorator['permissions']:
                        permissions_list.append(perm)
                        permission_to_endpoints[perm].append({
                            'path': route['path'],
                            'methods': route['methods'],
                            'note': 'any of these permissions'
                        })
                    protection_type = 'permission'
                elif decorator['type'] == 'require_authentication' and not has_permission:
                    protection_type = 'authentication'
                elif decorator['type'] == 'require_board_access' and not has_permission:
                    protection_type = 'board_access'

            endpoint_info = {
                'path': route['path'],
                'methods': route['methods'],
                'methods_str': methods_str,
                'protection': protection_type
            }

            if permissions_list:
                endpoint_info['permissions'] = list(dict.fromkeys(permissions_list))

            endpoint_to_permissions[endpoint_key] = endpoint_info

        for perm in permission_to_endpoints:
            seen = set()
            unique_endpoints = []
            for endpoint in permission_to_endpoints[perm]:
                key = (endpoint['path'], tuple(endpoint['methods']))
                if key not in seen:
                    seen.add(key)
                    unique_endpoints.append(endpoint)
            permission_to_endpoints[perm] = sorted(unique_endpoints, key=lambda x: x['path'])

        for perm in PERMISSION_DEFINITIONS.keys():
            permission_to_endpoints.setdefault(perm, [])

        sorted_permission_to_endpoints = dict(sorted(permission_to_endpoints.items()))
        sorted_endpoint_to_permissions = dict(sorted(endpoint_to_permissions.items()))

        permission_details = {}
        for perm in sorted(PERMISSION_DEFINITIONS.keys()):
            permission_details[perm] = {
                'description': PERMISSION_DEFINITIONS.get(perm, 'No description available'),
                'endpoint_count': len(permission_to_endpoints[perm])
            }

        summary = {
            'total_endpoints': len(all_routes),
            'permission_protected': len([e for e in endpoint_to_permissions.values() if e['protection'] == 'permission']),
            'authentication_only': len([e for e in endpoint_to_permissions.values() if e['protection'] == 'authentication']),
            'board_access': len([e for e in endpoint_to_permissions.values() if e['protection'] == 'board_access']),
            'public': len([e for e in endpoint_to_permissions.values() if e['protection'] == 'public']),
            'total_permissions': len(PERMISSION_DEFINITIONS)
        }

        logger.info(f"Successfully generated mappings: {summary}")

        return create_success_response(data={
            'by_permission': sorted_permission_to_endpoints,
            'by_endpoint': sorted_endpoint_to_permissions,
            'permission_details': permission_details,
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Error generating permission mappings: {e}", exc_info=True)
        return create_error_response(f"Error generating permission mappings: {str(e)}", 500)

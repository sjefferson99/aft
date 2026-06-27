"""
User management endpoints for administrators.

This module provides admin-only endpoints for:
- Viewing all users
- Approving/rejecting pending users
- Managing user roles
- Activating/deactivating users
"""

from flask import Blueprint, jsonify, request, g
from database import SessionLocal
from datetime_helpers import serialize_datetime
from models import User, Role, UserRole
from auth import ensure_global_role
from utils import (
    require_permission,
    create_error_response,
    create_success_response,
)
import logging

logger = logging.getLogger(__name__)

# Create blueprint for user management routes
user_mgmt_bp = Blueprint('user_mgmt', __name__, url_prefix='/api/users')


@user_mgmt_bp.route('', methods=['GET'])
@require_permission('user.manage')
def list_users():
    """
    List all users in the system.
    ---
    tags:
      - User Management
    parameters:
      - name: status
        in: query
        type: string
        enum: [pending, approved, all]
        default: all
        description: Filter users by status
    responses:
      200:
        description: List of users
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
                  email:
                    type: string
                  username:
                    type: string
                  display_name:
                    type: string
                  is_active:
                    type: boolean
                  is_approved:
                    type: boolean
                  email_verified:
                    type: boolean
                  oauth_provider:
                    type: string
                  created_at:
                    type: string
                    format: date-time
                  last_login_at:
                    type: string
                    format: date-time
                  roles:
                    type: array
                    items:
                      type: object
      403:
        description: Forbidden - requires user.manage permission
    """
    status_filter = request.args.get('status', 'all')
    
    db = SessionLocal()
    try:
        query = db.query(User)
        
        if status_filter == 'pending':
            query = query.filter(User.is_approved == False, User.is_active == True)
        elif status_filter == 'approved':
            query = query.filter(User.is_approved == True)
        
        users = query.order_by(User.created_at.desc()).all()
        
        users_data = []
        for user in users:
            # Get user's roles
            roles = db.query(Role).join(UserRole).filter(
                UserRole.user_id == user.id,
                UserRole.board_id.is_(None)  # Global roles only
            ).all()
            
            users_data.append({
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'display_name': user.display_name,
                'is_active': user.is_active,
                'is_approved': user.is_approved,
                'email_verified': user.email_verified,
                'oauth_provider': user.oauth_provider,
                'created_at': serialize_datetime(user.created_at),
                'last_login_at': serialize_datetime(user.last_login_at),
                'roles': [{'id': r.id, 'name': r.name} for r in roles]
            })
        
        return create_success_response(data={'users': users_data})

    finally:
        db.close()


@user_mgmt_bp.route('/assignable', methods=['GET'])
def list_assignable_users():
    """Return active approved users available for card assignment.

    Requires authentication only — no admin permission needed.
    Used by the Trello import member-mapping UI.
    ---
    tags:
      - Users
    responses:
      200:
        description: List of assignable users
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
                  display_name:
                    type: string
      401:
        description: Not authenticated
    """
    if not g.get('user'):
        return create_error_response("Not authenticated", 401)

    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(User.is_active.is_(True), User.is_approved.is_(True))
            .order_by(User.display_name, User.username)
            .all()
        )
        users_data = [
            {"id": u.id, "username": u.username, "display_name": u.display_name or u.username}
            for u in users
        ]
        return create_success_response(data={'users': users_data})
    finally:
        db.close()


@user_mgmt_bp.route('/pending', methods=['GET'])
@require_permission('user.manage')
def list_pending_users():
    """
    List all pending (unapproved) users.
    ---
    tags:
      - User Management
    responses:
      200:
        description: List of pending users
        schema:
          type: object
          properties:
            success:
              type: boolean
            users:
              type: array
              items:
                type: object
            count:
              type: integer
      403:
        description: Forbidden - requires user.manage permission
    """
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.is_approved == False,
            User.is_active == True
        ).order_by(User.created_at.desc()).all()
        
        users_data = [{
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'display_name': user.display_name,
          'is_active': user.is_active,
          'is_approved': user.is_approved,
          'created_at': serialize_datetime(user.created_at),
        } for user in users]
        
        return create_success_response(data={
            'users': users_data,
            'count': len(users_data)
        })
        
    finally:
        db.close()


@user_mgmt_bp.route('/<int:user_id>/approve', methods=['POST'])
@require_permission('user.manage')
def approve_user(user_id):
    """
    Approve a pending user account.
    ---
    tags:
      - User Management
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: ID of user to approve
    responses:
      200:
        description: User approved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      400:
        description: User is already approved
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: User not found
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            return create_error_response("User not found", 404)
        
        if user.is_approved:
            return create_error_response("User is already approved", 400)
        
        user.is_approved = True

        # Ensure approved users always receive baseline global roles.
        # - theme_user: manage personal theme copies
        # - board_creator: create and own new boards
        for role_name in ('theme_user', 'board_creator'):
            try:
                ensure_global_role(db, user.id, role_name)
            except ValueError:
                logger.warning("System role '%s' is not defined; approved user may miss baseline access", role_name)

        db.commit()

        logger.info(f"User approved: {user.email} (ID: {user.id}) by admin {g.user.id}")

        # TODO: Send approval notification email to user
        
        return create_success_response(
            message=f"User {user.username} has been approved",
            data={
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'username': user.username,
                    'display_name': user.display_name,
                    'is_active': user.is_active,
                    'is_approved': user.is_approved,
                }
            }
        )
        
    finally:
        db.close()


@user_mgmt_bp.route('/<int:user_id>/reject', methods=['POST'])
@require_permission('user.manage')
def reject_user(user_id):
    """
    Reject and delete a pending user account.
    ---
    tags:
      - User Management
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: ID of user to reject
    responses:
      200:
        description: User rejected and deleted
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      400:
        description: Cannot reject an approved user
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: User not found
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            return create_error_response("User not found", 404)
        
        if user.is_approved:
            return create_error_response(
                "Cannot reject an approved user. Use deactivate instead.",
                400
            )
        
        username = user.username
        email = user.email
        
        db.delete(user)
        db.commit()
        
        logger.info(f"User rejected and deleted: {email} (username: {username}) by admin {g.user.id}")
        
        return create_success_response(
            message=f"User {username} has been rejected and removed"
        )
        
    finally:
        db.close()


@user_mgmt_bp.route('/<int:user_id>/deactivate', methods=['POST'])
@require_permission('user.manage')
def deactivate_user(user_id):
    """
    Deactivate a user account (prevents login).
    ---
    tags:
      - User Management
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: ID of user to deactivate
    responses:
      200:
        description: User deactivated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      400:
        description: Cannot deactivate your own account
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: User not found
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            return create_error_response("User not found", 404)
        
        if user.id == g.user.id:
            return create_error_response("Cannot deactivate your own account", 400)
        
        user.is_active = False
        db.commit()
        
        logger.info(f"User deactivated: {user.email} (ID: {user.id}) by admin {g.user.id}")
        
        return create_success_response(
          message=f"User {user.username} has been deactivated",
          data={
            'user': {
              'id': user.id,
              'email': user.email,
              'username': user.username,
              'display_name': user.display_name,
              'is_active': user.is_active,
              'is_approved': user.is_approved,
            }
          }
        )
        
    finally:
        db.close()


@user_mgmt_bp.route('/<int:user_id>/activate', methods=['POST'])
@require_permission('user.manage')
def activate_user(user_id):
    """
    Reactivate a deactivated user account.
    ---
    tags:
      - User Management
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: ID of user to activate
    responses:
      200:
        description: User activated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: User not found
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            return create_error_response("User not found", 404)
        
        user.is_active = True
        db.commit()
        
        logger.info(f"User activated: {user.email} (ID: {user.id}) by admin {g.user.id}")
        
        return create_success_response(
          message=f"User {user.username} has been activated",
          data={
            'user': {
              'id': user.id,
              'email': user.email,
              'username': user.username,
              'display_name': user.display_name,
              'is_active': user.is_active,
              'is_approved': user.is_approved,
            }
          }
        )
        
    finally:
        db.close()


@user_mgmt_bp.route('/<int:user_id>/roles', methods=['POST'])
@require_permission('user.role')
def assign_role(user_id):
    """
    Assign a role to a user.
    ---
    tags:
      - User Management
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: ID of user
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - role_name
          properties:
            role_name:
              type: string
              description: Name of the role to assign
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
        description: Forbidden - requires user.role permission
      404:
        description: User or role not found
      409:
        description: Role already assigned
    """
    data = request.get_json()
    
    if not data or 'role_name' not in data:
        return create_error_response("role_name is required", 400)
    
    role_name = data['role_name']
    board_id = data.get('board_id')
    
    db = SessionLocal()
    try:
        # Check if role exists first (before any permission checks)
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            return create_error_response(f"Role '{role_name}' not found", 404)
        
        # Check if user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return create_error_response("User not found", 404)
        
        # Now check permissions
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
        
        # If user has only user.role permission (not role.manage), they can only assign roles they have
        if not has_role_manage:
            current_user_role_ids = get_user_role_ids(g.user.id, board_id)
            if role.id not in current_user_role_ids:
                return create_error_response(
                    f"You can only assign roles that you have been granted. You do not have the '{role_name}' role.",
                    403
                )
        
        # Check if role already assigned
        existing = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
            UserRole.board_id == board_id
        ).first()
        
        if existing:
            scope = f" on board {board_id}" if board_id else " (global)"
            return create_error_response(
                f"User already has role '{role_name}'{scope}",
                409
            )
        
        user_role = UserRole(
            user_id=user_id,
            role_id=role.id,
            board_id=board_id
        )
        db.add(user_role)
        db.commit()
        
        scope = f" on board {board_id}" if board_id else " (global)"
        logger.info(f"Role '{role_name}' assigned to user {user.email}{scope} by admin {g.user.id}")
        
        return create_success_response(
            message=f"Role '{role_name}' assigned to {user.username}"
        )
        
    finally:
        db.close()


@user_mgmt_bp.route('/<int:user_id>/roles/<int:role_id>', methods=['DELETE'])
@require_permission('user.role')
def remove_role(user_id, role_id):
    """
    Remove a role from a user.
    ---
    tags:
      - User Management
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: ID of user
      - name: role_id
        in: path
        type: integer
        required: true
        description: ID of role to remove
      - name: board_id
        in: query
        type: integer
        description: Optional board ID for board-specific roles
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
      403:
        description: Forbidden - requires user.role permission
      404:
        description: Role assignment not found
    """
    board_id = request.args.get('board_id', type=int)
    
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
        
        # If user has only user.role permission (not role.manage), they can only remove roles they have
        if not has_role_manage:
            current_user_role_ids = get_user_role_ids(g.user.id, board_id)
            if role_id not in current_user_role_ids:
                # Get role name for error message
                role = db.query(Role).filter(Role.id == role_id).first()
                role_name = role.name if role else "this role"
                return create_error_response(
                    f"You can only remove roles that you have been granted. You do not have the '{role_name}' role.",
                    403
                )
        
        assignment = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
            UserRole.board_id == board_id
        ).first()
        
        if not assignment:
            return create_error_response("Role assignment not found", 404)
        
        db.delete(assignment)
        db.commit()
        
        logger.info(f"Role removed from user {user_id} by admin {g.user.id}")
        
        return create_success_response(message="Role removed successfully")
        
    finally:
        db.close()

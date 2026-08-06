"""Utility functions for notification management."""
import logging
from flask import g, has_request_context
from database import SessionLocal
from models import Notification, Role, User, UserRole

logger = logging.getLogger(__name__)

# Shared with alembic/versions/034_add_mobile_app_notification.py - keep both in sync.
MOBILE_APP_NOTIFICATION_SUBJECT = 'Install AFT as an app'
MOBILE_APP_NOTIFICATION_MESSAGE = (
    "AFT can be installed as an app on your phone, tablet, Mac or PC for a "
    "full-screen, home-screen experience with no browser address bar. "
    "Mac/PC (Chrome or Edge): open AFT, then click the install icon in the "
    "address bar, or the browser menu > Install AFT. "
    "Android (Chrome): open AFT, tap the menu (three dots) > Install app, "
    "or use the Install App button in AFT Settings. "
    "iPhone/iPad (Safari): open AFT, tap the Share icon, then Add to Home "
    "Screen. See AFT Settings for step-by-step help."
)
MOBILE_APP_NOTIFICATION_ACTION_TITLE = 'Open Settings'
MOBILE_APP_NOTIFICATION_ACTION_URL = '/settings.html'


def create_mobile_app_notification(user_id: int) -> bool:
    """Create the 'install AFT as an app' notification for a single new user."""
    return create_notification(
        subject=MOBILE_APP_NOTIFICATION_SUBJECT,
        message=MOBILE_APP_NOTIFICATION_MESSAGE,
        action_title=MOBILE_APP_NOTIFICATION_ACTION_TITLE,
        action_url=MOBILE_APP_NOTIFICATION_ACTION_URL,
        user_id=user_id,
    )


def _resolve_recipient_user_ids(db, explicit_user_id=None):
    """Resolve recipient user IDs for internal notifications.

    Priority:
    1. Explicit user_id argument
    2. Current authenticated request user
    3. Active/approved users with global administrator role
    4. First active/approved user as last-resort fallback
    """
    if explicit_user_id is not None:
        return [explicit_user_id]

    if has_request_context() and getattr(g, 'user', None):
        return [g.user.id]

    admin_user_ids = (
        db.query(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            User.is_active.is_(True),
            User.is_approved.is_(True),
            Role.name == 'administrator',
            UserRole.board_id.is_(None),
        )
        .all()
    )
    resolved = [user_id for (user_id,) in admin_user_ids]
    if resolved:
        return resolved

    fallback_user = (
        db.query(User.id)
        .filter(User.is_active.is_(True), User.is_approved.is_(True))
        .order_by(User.id.asc())
        .first()
    )
    if fallback_user:
        return [fallback_user[0]]

    return []


def create_notification(subject: str, message: str, action_title: str = None, action_url: str = None, user_id: int = None) -> bool:
    """Create a notification in the database.
    
    This is a shared utility function for internal use (backup scheduler, 
    error handlers, etc.) to create notifications. Unlike the API endpoint 
    which validates and rejects oversized input, this function silently 
    truncates content that exceeds database column limits and logs an info message.
    
    This forgiving behavior is intentional for internal operations where
    notifications should not fail due to message length.
    
    Args:
        subject: Notification subject (truncated to 255 chars if longer)
        message: Notification message (truncated to 65535 chars if longer)
        action_title: Optional action button title (truncated to 100 chars if longer)
        action_url: Optional action button URL (truncated to 500 chars if longer)
        
    Returns:
        True if notification created successfully, False otherwise
        
    Note:
        If truncation occurs, an info message is logged with details about
        the truncated content.
    """
    from security_validators import validate_safe_url
    
    db = SessionLocal()
    try:
        # Preserve original values before any processing
        original_subject_raw = subject
        original_message_raw = message
        original_action_title_raw = action_title
        original_action_url_raw = action_url
        
        # Strip whitespace
        subject = subject.strip()
        message = message.strip()
        
        # Truncate subject and message
        subject = subject[:255]
        message = message[:65535]
        
        # Process action fields if provided
        if action_title is not None:
            action_title = action_title.strip()
            # Set to None if empty after stripping
            if not action_title:
                action_title = None
            elif len(action_title) > 100:
                # Log truncation before truncating
                truncated_chars = len(action_title) - 100
                preview_suffix = '...' if len(action_title) > 50 else ''
                logger.info(
                    f"Notification action_title truncated: {truncated_chars} characters removed. "
                    f"Original: '{action_title[:50]}{preview_suffix}', "
                    f"Truncated: '{action_title[:100][:50]}{preview_suffix}'"
                )
                action_title = action_title[:100]
            
        if action_url is not None:
            action_url = action_url.strip()
            # Set to None if empty after stripping
            if not action_url:
                action_url = None
            else:
                # Truncate first
                if len(action_url) > 500:
                    truncated_chars = len(action_url) - 500
                    preview_suffix = '...' if len(action_url) > 50 else ''
                    logger.info(
                        f"Notification action_url truncated: {truncated_chars} characters removed. "
                        f"Original: '{action_url[:50]}{preview_suffix}', "
                        f"Truncated: '{action_url[:500][:50]}{preview_suffix}'"
                    )
                    action_url = action_url[:500]
                
                # Validate URL safety on the (possibly truncated) value
                is_valid, error_msg = validate_safe_url(action_url)
                if not is_valid:
                    logger.warning(f"Notification action_url rejected due to unsafe protocol: {action_url[:50]}")
                    action_url = None
        
        # Log info messages if truncation occurred (INFO level for routine internal operations)
        if len(original_subject_raw.strip()) > 255:
            truncated_chars = len(original_subject_raw.strip()) - 255
            preview_suffix = '...' if len(original_subject_raw.strip()) > 50 else ''
            logger.info(
                f"Notification subject truncated: {truncated_chars} characters removed. "
                f"Original: '{original_subject_raw.strip()[:50]}{preview_suffix}', "
                f"Truncated: '{subject[:50]}{preview_suffix}'"
            )
        
        if len(original_message_raw.strip()) > 65535:
            truncated_chars = len(original_message_raw.strip()) - 65535
            logger.info(
                f"Notification message truncated: {truncated_chars} characters removed. "
                f"Original length: {len(original_message_raw.strip())}, Truncated length: {len(message)}"
            )
        
        if not subject or not message:
            logger.warning("Attempted to create notification with empty subject or message")
            return False
        
        recipient_user_ids = _resolve_recipient_user_ids(db, explicit_user_id=user_id)
        if not recipient_user_ids:
            logger.warning("No eligible recipient users found for notification")
            return False

        for recipient_user_id in recipient_user_ids:
            notification = Notification(
                subject=subject,
                message=message,
                unread=True,
                action_title=action_title,
                action_url=action_url,
                user_id=recipient_user_id,
            )
            db.add(notification)

        db.commit()
        logger.info(f"Created notification for {len(recipient_user_ids)} recipient(s): {subject}")
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating notification: {str(e)}")
        return False
    finally:
        db.close()

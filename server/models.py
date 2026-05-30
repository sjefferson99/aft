"""Database models."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
from datetime_helpers import serialize_datetime
import json


class Theme(Base):
    """Theme model representing a color theme."""
    
    __tablename__ = "themes"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    settings = Column(Text, nullable=False)  # JSON string
    background_image = Column(String(255), nullable=True)
    system_theme = Column(Boolean, nullable=False, default=False)
    global_theme = Column(Boolean, nullable=False, default=False)
    
    # NULL user_id = system theme, otherwise user's custom theme
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)
    
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    
    __table_args__ = (
        # System themes (user_id is NULL) share scope 0; user themes are unique per user_id
        # Use COALESCE to normalize NULL user_id to 0, ensuring global uniqueness
        Index('idx_theme_owner_scope_name', func.coalesce(user_id, 0), 'name', unique=True),
    )
    
    def to_dict(self):
        """Convert theme to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'settings': json.loads(self.settings) if isinstance(self.settings, str) else self.settings,
            'background_image': self.background_image,
            'system_theme': self.system_theme,
            'global_theme': self.global_theme,
            'created_at': serialize_datetime(self.created_at),
            'updated_at': serialize_datetime(self.updated_at)
        }
    
    def __repr__(self):
        return f"<Theme(id={self.id}, name='{self.name}', system_theme={self.system_theme})>"



class Board(Base):
    """Board model representing a board in the system."""
    
    __tablename__ = "boards"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_public = Column(Boolean, nullable=False, default=False)
    public_slug = Column(String(64), nullable=True, unique=True, index=True)
    
    # Owner has full control over the board
    owner_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)
    
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    
    # Relationships
    owner = relationship("User", back_populates="owned_boards", foreign_keys=[owner_id])
    columns = relationship("BoardColumn", back_populates="board", cascade="all, delete-orphan")
    settings = relationship("BoardSetting", back_populates="board", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Board(id={self.id}, name='{self.name}')>"


class BoardColumn(Base):
    """Column model representing a column within a board."""
    
    __tablename__ = "columns"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    board_id = Column(Integer, ForeignKey('boards.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    
    # Relationship to board
    board = relationship("Board", back_populates="columns")
    
    # Relationship to cards
    cards = relationship("Card", back_populates="column", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<BoardColumn(id={self.id}, board_id={self.board_id}, name='{self.name}', order={self.order})>"


class Card(Base):
    """Card model representing a task card within a column."""
    
    __tablename__ = "cards"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    column_id = Column(Integer, ForeignKey('columns.id', ondelete='CASCADE'), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String(2000), nullable=True)
    order = Column(Integer, nullable=False, default=0)
    archived = Column(Boolean, nullable=False, default=False, index=True)
    scheduled = Column(Boolean, nullable=False, default=False, index=True)
    schedule = Column(Integer, ForeignKey('scheduled_cards.id', ondelete='SET NULL'), nullable=True, index=True)
    done = Column(Boolean, nullable=False, default=False, index=True)
    
    # Track who created the card (inherits board ownership for access)
    created_by_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    
    # Optional: assign card to specific user
    assigned_to_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    
    # Relationship to column
    column = relationship("BoardColumn", back_populates="cards")
    
    # Relationship to checklist items
    checklist_items = relationship("ChecklistItem", back_populates="card", cascade="all, delete-orphan", order_by="ChecklistItem.order")
    
    # Relationship to comments (newest first)
    comments = relationship("Comment", back_populates="card", cascade="all, delete-orphan", order_by="Comment.order.desc()")
    
    # Relationship to schedule (one-to-one for template cards)
    # passive_deletes=True tells SQLAlchemy to rely on database CASCADE instead of trying to SET NULL
    schedule_config = relationship("ScheduledCard", foreign_keys="ScheduledCard.card_id", back_populates="template_card", uselist=False, passive_deletes=True)
    
    # Relationship to the schedule this card was created from (many cards can be created from one schedule)
    created_from_schedule = relationship("ScheduledCard", foreign_keys=[schedule], back_populates="created_cards")
    
    # Relationships to assignees
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    secondary_assignees = relationship("CardSecondaryAssignee", back_populates="card", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Card(id={self.id}, column_id={self.column_id}, title='{self.title}', order={self.order}, scheduled={self.scheduled})>"


class CardSecondaryAssignee(Base):
    """Maps secondary assignees to a card."""
    
    __tablename__ = "card_secondary_assignees"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    card_id = Column(Integer, ForeignKey('cards.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=True)
    
    card = relationship("Card", back_populates="secondary_assignees")
    user = relationship("User")
    
    __table_args__ = (
        Index('idx_card_secondary_assignee_unique', 'card_id', 'user_id', unique=True),
    )
    
    def __repr__(self):
        return f"<CardSecondaryAssignee(card_id={self.card_id}, user_id={self.user_id})>"


class ChecklistItem(Base):
    """ChecklistItem model representing a checklist item within a card."""
    
    __tablename__ = "checklist_items"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    card_id = Column(Integer, ForeignKey('cards.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    checked = Column(Boolean, nullable=False, default=False)
    order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    
    # Relationship to card
    card = relationship("Card", back_populates="checklist_items")
    
    def __repr__(self):
        return f"<ChecklistItem(id={self.id}, card_id={self.card_id}, name='{self.name}', checked={self.checked}, order={self.order})>"


class Setting(Base):
    """Setting model for storing application settings."""
    
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column("key", String(255), nullable=False, index=True)  # 'key' is a MySQL reserved word
    value = Column("value", Text, nullable=True)  # Quote for consistency
    
    # NULL user_id = global/system setting
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)
    
    __table_args__ = (
        # Each user can have one value per setting key; normalize NULL user_id to 0 for global uniqueness
        Index('idx_setting_scope_key', func.coalesce(user_id, 0), 'key', unique=True),
    )
    
    def __repr__(self):
        return f"<Setting(id={self.id}, key='{self.key}')>"


class InstanceConfig(Base):
    """InstanceConfig model for storing global instance configuration."""

    __tablename__ = "instance_config"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(255), nullable=False, unique=True, index=True)
    value = Column(String(1024), nullable=True)

    def __repr__(self):
        return f"<InstanceConfig(id={self.id}, key='{self.key}')>"


class BoardSetting(Base):
    """BoardSetting model for storing board-specific configuration."""

    __tablename__ = "board_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    board_id = Column(Integer, ForeignKey('boards.id', ondelete='CASCADE'), nullable=False, index=True)
    key = Column("key", String(255), nullable=False, index=True)
    value = Column("value", Text, nullable=True)

    board = relationship("Board", back_populates="settings")

    __table_args__ = (
        Index('idx_board_setting_key', 'board_id', 'key', unique=True),
    )

    def __repr__(self):
        return f"<BoardSetting(id={self.id}, board_id={self.board_id}, key='{self.key}')>"


class Comment(Base):
    """Comment model representing a journal comment on a card."""
    
    __tablename__ = "comments"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    card_id = Column(Integer, ForeignKey('cards.id', ondelete='CASCADE'), nullable=False, index=True)
    comment = Column(Text, nullable=False)  # Large text field for comments
    order = Column(Integer, nullable=False, index=True)  # Immutable order to preserve history
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    
    # Relationship to card
    card = relationship("Card", back_populates="comments")
    
    def __repr__(self):
        return f"<Comment(id={self.id}, card_id={self.card_id}, order={self.order})>"


class Notification(Base):
    """Notification model representing user notifications."""
    
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    unread = Column(Boolean, nullable=False, default=True, index=True)
    
    # REQUIRED: notifications belong to specific users
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    action_title = Column(String(100), nullable=True)
    action_url = Column(String(500), nullable=True)
    
    def __repr__(self):
        return f"<Notification(id={self.id}, subject='{self.subject}', unread={self.unread})>"


class ScheduledCard(Base):
    """ScheduledCard model representing a card scheduling configuration."""
    
    __tablename__ = "scheduled_cards"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    card_id = Column(Integer, ForeignKey('cards.id', ondelete='CASCADE'), nullable=False, index=True)
    run_every = Column(Integer, nullable=False)
    unit = Column(String(10), nullable=False)  # minute, hour, day, week, month, year
    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime, nullable=True)
    schedule_enabled = Column(Boolean, nullable=False, default=True, index=True)
    allow_duplicates = Column(Boolean, nullable=False, default=False)
    
    # Relationship to the template card (one-to-one)
    template_card = relationship("Card", foreign_keys=[card_id], back_populates="schedule_config")
    
    # Relationship to cards created from this schedule (one-to-many)
    created_cards = relationship("Card", foreign_keys="Card.schedule", back_populates="created_from_schedule")
    
    def __repr__(self):
        return f"<ScheduledCard(id={self.id}, card_id={self.card_id}, run_every={self.run_every}, unit='{self.unit}', enabled={self.schedule_enabled})>"


class User(Base):
    """User account model."""
    
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    username = Column(String(100), nullable=True, unique=True, index=True)
    display_name = Column(String(255), nullable=True)
    
    # OAuth fields (nullable for initial implementation)
    oauth_provider = Column(String(50), nullable=True)  # 'google', 'github', etc.
    oauth_sub = Column(String(255), nullable=True, index=True)  # Provider's user ID
    
    # Password hash (nullable when using OAuth)
    password_hash = Column(String(255), nullable=True)
    
    # Status
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_approved = Column(Boolean, nullable=False, default=False, index=True)  # Admin must approve new users
    email_verified = Column(Boolean, nullable=False, default=False)
    
    # Profile
    profile_colour = Column(String(7), nullable=False, server_default='#90A4AE')

    # Timestamps
    created_at = Column(DateTime, server_default=func.current_timestamp())
    last_login_at = Column(DateTime, nullable=True)
    
    # Relationships
    role_assignments = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    owned_boards = relationship("Board", back_populates="owner", foreign_keys="Board.owner_id")
    
    __table_args__ = (
        # Ensure oauth_provider + oauth_sub combination is unique
        Index('idx_oauth_provider_sub', 'oauth_provider', 'oauth_sub', unique=True),
    )
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', username='{self.username}')>"


class Role(Base):
    """Role definition model."""
    
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    
    # System roles can't be deleted/modified by users
    is_system_role = Column(Boolean, nullable=False, default=False)
    
    # Permissions as JSON array for flexibility
    permissions = Column(Text, nullable=False)  # JSON array of permission strings
    
    created_at = Column(DateTime, server_default=func.current_timestamp())
    
    # Relationships
    user_assignments = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}', is_system={self.is_system_role})>"


class UserRole(Base):
    """User role assignment model (many-to-many with context)."""
    
    __tablename__ = "user_roles"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey('roles.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Optional: scope role to specific board (NULL = global role)
    board_id = Column(Integer, ForeignKey('boards.id', ondelete='CASCADE'), nullable=True, index=True)
    
    created_at = Column(DateTime, server_default=func.current_timestamp())
    
    # Relationships
    user = relationship("User", back_populates="role_assignments")
    role = relationship("Role", back_populates="user_assignments")
    board = relationship("Board", foreign_keys=[board_id])
    
    __table_args__ = (
        # A user can only have one instance of a role per board (or globally)
        Index('idx_user_role_board', 'user_id', 'role_id', 'board_id', unique=True),
    )
    
    def __repr__(self):
        return f"<UserRole(id={self.id}, user_id={self.user_id}, role_id={self.role_id}, board_id={self.board_id})>"

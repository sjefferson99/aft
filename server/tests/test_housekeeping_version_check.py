"""Unit tests for the housekeeping release notification check (issue #408)."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import housekeeping_scheduler
from housekeeping_scheduler import HousekeepingScheduler
from models import Notification

# Mark all tests in this module as unit tests (don't wait for API)
pytestmark = pytest.mark.unit

RUNNING_VERSION = "1.0.0"
LATEST_VERSION = "1.1.0"


def release_subject(release_version):
    """Build the subject the scheduler gives a release notification."""
    return f"New Version Available: {release_version}"


@pytest.fixture
def session_factory(monkeypatch):
    """Point the scheduler's query at an in-memory notifications table."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Notification.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("database.SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture
def notify(monkeypatch):
    """Replace create_notification so tests can see whether it was called."""
    mock = MagicMock(return_value=True)
    monkeypatch.setattr(housekeeping_scheduler, "create_notification", mock)
    return mock


@pytest.fixture(autouse=True)
def github_release(monkeypatch):
    """Report LATEST_VERSION as the latest GitHub release."""
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "tag_name": f"v{LATEST_VERSION}",
        "html_url": "https://github.com/sjefferson99/aft/releases/tag/v1.1.0",
    }
    monkeypatch.setattr(
        housekeeping_scheduler.requests, "get", MagicMock(return_value=response)
    )


def add_notification(session_factory, subject, unread, user_id=1):
    """Store a notification as if it had been created earlier."""
    session = session_factory()
    try:
        session.add(
            Notification(subject=subject, message="m", unread=unread, user_id=user_id)
        )
        session.commit()
    finally:
        session.close()


class TestReleaseNotificationDuplicates:
    """Tests for when _check_for_updates creates a release notification."""

    def test_notifies_when_no_notification_exists(self, session_factory, notify):
        """A new release is announced, including after the notification is deleted."""
        HousekeepingScheduler(RUNNING_VERSION)._check_for_updates()

        notify.assert_called_once()
        assert notify.call_args.kwargs["subject"] == release_subject(LATEST_VERSION)

    def test_no_duplicate_when_notification_is_unread(self, session_factory, notify):
        """An unread notification for the release suppresses another."""
        add_notification(session_factory, release_subject(LATEST_VERSION), unread=True)

        HousekeepingScheduler(RUNNING_VERSION)._check_for_updates()

        notify.assert_not_called()

    def test_no_duplicate_when_notification_is_read(self, session_factory, notify):
        """A read notification for the release also suppresses another (#408)."""
        add_notification(session_factory, release_subject(LATEST_VERSION), unread=False)

        HousekeepingScheduler(RUNNING_VERSION)._check_for_updates()

        notify.assert_not_called()

    def test_no_duplicate_when_any_admin_has_it_read(self, session_factory, notify):
        """A copy kept by one admin suppresses another, whoever else deleted theirs."""
        add_notification(
            session_factory, release_subject(LATEST_VERSION), unread=False, user_id=2
        )

        HousekeepingScheduler(RUNNING_VERSION)._check_for_updates()

        notify.assert_not_called()

    def test_older_release_notification_does_not_suppress(self, session_factory, notify):
        """A notification for an earlier release doesn't hide a newer one."""
        add_notification(session_factory, release_subject("1.0.5"), unread=False)

        HousekeepingScheduler(RUNNING_VERSION)._check_for_updates()

        notify.assert_called_once()

    def test_no_notification_when_up_to_date(self, session_factory, notify):
        """Nothing is announced when already on the latest release."""
        HousekeepingScheduler(LATEST_VERSION)._check_for_updates()

        notify.assert_not_called()

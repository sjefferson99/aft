"""Automatic card scheduler service."""
import os
import threading
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import logging

from sqlalchemy import func, text
from database import SessionLocal
from datetime_helpers import serialize_datetime, utc_now
from models import Card, ScheduledCard, Comment, ChecklistItem, BoardColumn
from notification_utils import create_notification
from schedule_utils import get_next_run
from scheduler_lock import (
    acquire_scheduler_lock,
    release_scheduler_lock,
    update_scheduler_heartbeat,
)

logger = logging.getLogger(__name__)

MAX_REGENERATION_RUNS_PER_SCHEDULE = 10000


_broadcast_event_callback = None


def set_broadcast_event_callback(callback):
    """Register a websocket broadcaster callback.

    The callback must have signature: (event_name, data, board_id, skip_sid=None).
    """
    global _broadcast_event_callback
    _broadcast_event_callback = callback


class CardScheduler:
    """Manages automatic card creation on a schedule."""
    
    def __init__(self):
        import tempfile
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock_file = Path(tempfile.gettempdir()) / "aft_card_scheduler.lock"
    
    def _update_heartbeat(self):
        """Update lock file with current timestamp to prove thread is alive."""
        update_scheduler_heartbeat(self.lock_file, "card")

    def _acquire_lock(self) -> bool:
        """Attempt to acquire the scheduler lock with diagnostics."""
        acquired, details = acquire_scheduler_lock(
            lock_file=self.lock_file,
            scheduler_type="card",
            stale_after_seconds=300,
        )
        if acquired:
            logger.info("Card scheduler lock acquired: %s", details)
            return True

        logger.info("Card scheduler lock acquisition skipped: %s", details)
        return False

    def _release_lock(self):
        """Release the scheduler lock."""
        release_scheduler_lock(self.lock_file)
    
    def start(self):
        """Start the card scheduler in a background thread."""
        logger.info("=== Card Scheduler Start Attempt ===")
        logger.info(f"PID: {os.getpid()}, Container: {os.environ.get('HOSTNAME', 'unknown')}")
        
        if self.running:
            logger.warning("Card scheduler is already running in this instance")
            return
        
        if not self._acquire_lock():
            logger.info("Could not acquire card scheduler lock - another instance is active")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"✓ Card scheduler started successfully - PID: {os.getpid()}, Thread ID: {self.thread.ident}")
    
    def stop(self):
        """Stop the card scheduler."""
        if not self.running:
            return
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        
        self._release_lock()
        logger.info("Card scheduler stopped")
    
    def _run(self):
        """Main scheduler loop - runs every minute."""
        logger.info("Card scheduler loop started")
        
        while self.running:
            try:
                # Update heartbeat to prove we're alive
                self._update_heartbeat()
                
                # Check if card scheduler is enabled
                if self._is_enabled():
                    self._check_and_create_cards()
                else:
                    logger.debug("Card scheduler is disabled, skipping card creation")
            except Exception as e:
                logger.error(f"Error in card scheduler loop: {str(e)}")
                create_notification(
                    subject="❌ Card Scheduler Error",
                    message=f"An error occurred in the card scheduler:\n\n{str(e)}\n\nThe scheduler will continue running, but please check the logs."
                )
            
            # Sleep for 60 seconds
            for _ in range(60):
                if not self.running:
                    break
                time.sleep(1)
    
    def _is_enabled(self) -> bool:
        """Check if card scheduler is enabled in settings."""
        try:
            import json
            from models import Setting
            
            db = SessionLocal()
            try:
                setting = db.query(Setting).filter(Setting.key == "card_scheduler_enabled").first()
                if setting is not None and setting.value is not None:
                    return json.loads(str(setting.value))
                return True  # Default to enabled
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error checking card_scheduler_enabled setting: {e}")
            return True  # Default to enabled on error
    
    def _build_schedule_run_lock_key(self, schedule_id: int, run_time: datetime) -> str:
        """Build a stable lock key per schedule run window."""
        return f"aft_sched_{schedule_id}_{run_time.strftime('%Y%m%d%H%M')}"

    def _acquire_schedule_run_lock(self, db, lock_key: str) -> bool:
        """Acquire a DB advisory lock to prevent duplicate card creation across workers."""
        try:
            result = db.execute(text("SELECT GET_LOCK(:lock_key, 0)"), {"lock_key": lock_key}).scalar()
            acquired = bool(result == 1)
            if not acquired:
                logger.info("Schedule run lock is already held, skipping duplicate run: lock_key=%s", lock_key)
            return acquired
        except Exception as exc:
            logger.warning("Failed to acquire schedule run lock %s: %s", lock_key, exc)
            return False

    def _release_schedule_run_lock(self, db, lock_key: str) -> None:
        """Release a DB advisory lock after schedule processing."""
        try:
            db.execute(text("SELECT RELEASE_LOCK(:lock_key)"), {"lock_key": lock_key})
        except Exception as exc:
            logger.warning("Failed to release schedule run lock %s: %s", lock_key, exc)

    def _check_and_create_cards(self):
        """Check all enabled schedules and create cards if needed."""
        db = SessionLocal()
        pending_broadcasts = []
        try:
            # Schedule datetimes are stored as naive UTC values; compare in UTC.
            now = utc_now()
            
            # Get all enabled schedules
            schedules = (
                db.query(ScheduledCard)
                .filter(ScheduledCard.schedule_enabled.is_(True))
                .all()
            )
            
            for schedule in schedules:
                try:
                    self._process_schedule(db, schedule, now, pending_broadcasts)
                except Exception as e:
                    logger.error(f"Error processing schedule {schedule.id}: {str(e)}")
                    # Continue with other schedules
            
            db.commit()

            # Emit websocket updates only after the transaction commits successfully.
            for event_data in pending_broadcasts:
                self._broadcast_event(
                    event_name='card_created',
                    data=event_data,
                    board_id=event_data['board_id']
                )
            
        except Exception as e:
            logger.error(f"Error checking schedules: {str(e)}")
            db.rollback()
        finally:
            db.close()
    
    def _process_schedule(self, db, schedule: ScheduledCard, now: datetime, pending_broadcasts: list):
        """Process a single schedule and create card if needed.
        
        This method implements a catch-up mechanism to handle missed schedules:
        - Looks back up to 1 hour to find the most recent scheduled run time
        - Creates the card if we're within 1 minute of any missed run time
        - Only creates ONE card per missed window to prevent duplicates
        
        Limitations:
        - If the server is down for more than 1 hour, schedules in that period won't be caught up
        - Only catches up the most recent missed run, not all missed runs
        - Relies on checking the database for existing cards to prevent duplicates
        
        Args:
            db: Database session
            schedule: ScheduledCard instance
            now: Current datetime
            pending_broadcasts: List of websocket events queued for post-commit publish
        """
        # Check if we're past the start time
        if now < schedule.start_datetime:  # type: ignore
            return
        
        # Check if we're past the end time (if set)
        if schedule.end_datetime is not None:
            if now > schedule.end_datetime:  # type: ignore
                # Disable the schedule
                if schedule.schedule_enabled:  # type: ignore
                    schedule.schedule_enabled = False  # type: ignore
                    logger.info(f"Disabled schedule {schedule.id} - past end time")
                    create_notification(
                        subject="⏰ Schedule Ended",
                        message=f"The schedule for card '{schedule.template_card.title}' has been automatically disabled because it reached its end time."
                    )
                return
        
        # Calculate next run time - check if we should run now
        # Look back up to 1 hour to catch any runs we might have missed due to:
        # - Server restarts
        # - Heavy load causing delayed execution
        # - Temporary service interruptions
        # This provides a reasonable catch-up window without going too far back
        lookback_window = timedelta(hours=1)
        check_time = now - lookback_window
        
        next_run = get_next_run(
            start=schedule.start_datetime,  # type: ignore
            after=check_time,
            run_every=schedule.run_every,  # type: ignore
            unit=schedule.unit  # type: ignore
        )
        
        # Check if it's time to create a card
        # We create a card if the calculated next_run is in the past but within our lookback window.
        if next_run and next_run <= now:
            time_since_run = (now - next_run).total_seconds()
            if time_since_run >= lookback_window.total_seconds():
                logger.debug(f"Skipping schedule {schedule.id} - next_run too old ({time_since_run:.0f} seconds ago)")
                return

            run_lock_key = self._build_schedule_run_lock_key(schedule.id, next_run)  # type: ignore[arg-type]
            if not self._acquire_schedule_run_lock(db, run_lock_key):
                return

            try:
                # Additional safety when duplicates are not allowed.
                if not schedule.allow_duplicates:  # type: ignore
                    template = db.query(Card).filter(Card.id == schedule.card_id).first()
                    if not template:
                        logger.error(f"Template card {schedule.card_id} not found for schedule {schedule.id}")
                        return

                    existing_card = (
                        db.query(Card)
                        .filter(Card.column_id == template.column_id)
                        .filter(Card.schedule == schedule.id)
                        .filter(Card.scheduled.is_(False))
                        .filter(Card.archived.is_(False))
                        .first()
                    )

                    if existing_card:
                        logger.debug(
                            "Skipping schedule %s - active card %s already exists in column %s",
                            schedule.id,
                            existing_card.id,
                            template.column_id,
                        )
                        return

                logger.info(
                    "Creating card for schedule %s (missed_by=%.0fs, run_lock=%s)",
                    schedule.id,
                    time_since_run,
                    run_lock_key,
                )
                self._create_scheduled_card(db, schedule, pending_broadcasts)
            finally:
                self._release_schedule_run_lock(db, run_lock_key)

    def _iter_schedule_runs_in_range(
        self,
        schedule: ScheduledCard,
        range_start: datetime,
        range_end: datetime,
        *,
        max_runs: int,
    ) -> list[datetime]:
        """Expand a schedule into all run times that fall inside a requested range."""
        schedule_start = schedule.start_datetime  # type: ignore[assignment]
        schedule_end = schedule.end_datetime  # type: ignore[assignment]

        if schedule_start is None:
            return []

        effective_start = max(range_start, schedule_start)
        effective_end = range_end
        if schedule_end is not None:
            effective_end = min(effective_end, schedule_end)

        if effective_end < effective_start:
            return []

        run_times: list[datetime] = []
        candidate = get_next_run(
            start=schedule_start,
            after=effective_start,
            run_every=schedule.run_every,  # type: ignore[arg-type]
            unit=schedule.unit  # type: ignore[arg-type]
        )

        iterations = 0
        while candidate is not None and candidate <= effective_end:
            if iterations >= max_runs:
                raise ValueError(
                    f"Regeneration request exceeds the maximum allowed runs per schedule ({max_runs}). Narrow the date range or reduce schedule frequency."
                )
            run_times.append(candidate)
            iterations += 1

            previous_candidate = candidate
            candidate = get_next_run(
                start=schedule_start,
                after=previous_candidate + timedelta(microseconds=1),
                run_every=schedule.run_every,  # type: ignore[arg-type]
                unit=schedule.unit  # type: ignore[arg-type]
            )
            if candidate is not None and candidate <= previous_candidate:
                break

        return run_times

    def _build_schedule_run_preview_item(
        self,
        schedule: ScheduledCard,
        run_time: datetime,
        template: Card,
        column: Optional[BoardColumn],
    ) -> dict[str, Any]:
        """Build preview metadata for a run that can produce a card."""
        board = column.board if column else None

        return {
            "run_at": serialize_datetime(run_time),
            "schedule_id": schedule.id,
            "template_card_id": template.id,
            "template_card_title": template.title,
            "board_id": board.id if board else None,
            "board_name": board.name if board else None,
            "column_id": column.id if column else template.column_id,
            "column_name": column.name if column else None,
            "frequency": {
                "run_every": schedule.run_every,
                "unit": schedule.unit,
            },
            "allow_duplicates": bool(schedule.allow_duplicates),
        }

    def _get_schedule_preview_context(
        self,
        db,
        schedule: ScheduledCard,
    ) -> tuple[Card, Optional[BoardColumn]] | tuple[None, None]:
        """Load schedule preview context once per schedule to avoid N+1 queries."""
        template = db.query(Card).filter(Card.id == schedule.card_id).first()
        if not template:
            logger.error(f"Template card {schedule.card_id} not found for schedule {schedule.id}")
            return None, None

        column = db.query(BoardColumn).filter(BoardColumn.id == template.column_id).first()
        return template, column

    def regenerate_for_range(
        self,
        range_start: datetime,
        range_end: datetime,
        *,
        preview_only: bool,
    ) -> dict[str, Any]:
        """Preview or create scheduled cards for all enabled schedules within a custom date range."""
        db = SessionLocal()
        pending_broadcasts: list[dict[str, Any]] = []
        preview_items: list[dict[str, Any]] = []
        generated_count = 0
        runs_considered = 0

        try:
            schedules = (
                db.query(ScheduledCard)
                .filter(ScheduledCard.schedule_enabled.is_(True))
                .all()
            )

            for schedule in schedules:
                template, column = self._get_schedule_preview_context(db, schedule)
                if template is None:
                    continue

                run_times = self._iter_schedule_runs_in_range(
                    schedule,
                    range_start,
                    range_end,
                    max_runs=MAX_REGENERATION_RUNS_PER_SCHEDULE,
                )

                if not schedule.allow_duplicates:  # type: ignore
                    existing_card = (
                        db.query(Card)
                        .filter(Card.column_id == template.column_id)
                        .filter(Card.schedule == schedule.id)
                        .filter(Card.scheduled.is_(False))
                        .filter(Card.archived.is_(False))
                        .first()
                    )
                    if existing_card:
                        continue
                    if run_times:
                        # Only the first run can produce a new card when duplicates are disallowed.
                        run_times = run_times[:1]

                for run_time in run_times:
                    runs_considered += 1
                    preview_item = self._build_schedule_run_preview_item(schedule, run_time, template, column)

                    preview_items.append(preview_item)

                    if preview_only:
                        continue

                    run_lock_key = self._build_schedule_run_lock_key(schedule.id, run_time)  # type: ignore[arg-type]
                    if not self._acquire_schedule_run_lock(db, run_lock_key):
                        continue

                    try:
                        created_card = self._create_scheduled_card(db, schedule, pending_broadcasts)
                        if created_card is not None:
                            generated_count += 1
                    finally:
                        self._release_schedule_run_lock(db, run_lock_key)

            preview_items.sort(key=lambda item: item["run_at"])

            if preview_only:
                db.rollback()
            else:
                db.commit()
                for event_data in pending_broadcasts:
                    self._broadcast_event(
                        event_name='card_created',
                        data=event_data,
                        board_id=event_data['board_id']
                    )

            return {
                "range_start": serialize_datetime(range_start),
                "range_end": serialize_datetime(range_end),
                "runs_considered": runs_considered,
                "would_generate_count": len(preview_items),
                "generated_count": generated_count,
                "cards": preview_items,
            }

        except Exception as e:
            db.rollback()
            logger.error(f"Error regenerating scheduled cards for range: {str(e)}")
            raise
        finally:
            db.close()

    def _broadcast_event(self, event_name: str, data: dict, board_id: int):
        """Broadcast websocket event via injected callback when available."""
        if _broadcast_event_callback is None:
            logger.warning(
                f"Skipping scheduler websocket broadcast for {event_name}: no broadcaster callback is registered"
            )
            return

        _broadcast_event_callback(event_name, data, board_id)
    
    def _create_scheduled_card(self, db, schedule: ScheduledCard, pending_broadcasts: list) -> Optional[Card]:
        """Create a new card from a schedule template.
        
        Args:
            db: Database session
            schedule: ScheduledCard instance
            pending_broadcasts: List of websocket events queued for post-commit publish
        """
        try:
            # Get the template card
            template = db.query(Card).filter(Card.id == schedule.card_id).first()
            if not template:
                logger.error(f"Template card {schedule.card_id} not found for schedule {schedule.id}")
                return None
            
            # Check for duplicates if not allowed
            if not schedule.allow_duplicates:  # type: ignore
                # Check for unarchived cards in the same column with this schedule ID
                existing_count = (
                    db.query(Card)
                    .filter(Card.column_id == template.column_id)
                    .filter(Card.schedule == schedule.id)
                    .filter(Card.archived.is_(False))
                    .filter(Card.scheduled.is_(False))  # Don't count template cards
                    .count()
                )
                
                if existing_count > 0:
                    logger.info(f"Skipping card creation for schedule {schedule.id} - duplicate exists in column")
                    return None
            
            # Get the highest order in the column for new cards
            max_order = db.query(func.max(Card.order)).filter(
                Card.column_id == template.column_id,
                Card.scheduled.is_(False)  # Only consider real cards, not templates
            ).scalar() or 0
            
            # Create new card from template
            new_card = Card(
                column_id=template.column_id,
                title=template.title,
                description=template.description,
                order=max_order + 1,
                archived=False,
                scheduled=False,  # This is a real card, not a template
                schedule=schedule.id  # Link back to the schedule
            )
            
            db.add(new_card)
            db.flush()  # Get the new card ID
            
            # Copy checklist items
            for item in template.checklist_items:
                new_item = ChecklistItem(
                    card_id=new_card.id,
                    name=item.name,
                    checked=item.checked,
                    order=item.order
                )
                db.add(new_item)
            
            # Add a comment to track creation
            # Get the highest comment order
            max_comment_order = db.query(func.max(Comment.order)).filter(
                Comment.card_id == new_card.id
            ).scalar() or 0
            
            comment_text = (
                f"🤖 Created by scheduling system\n\n"
                f"Schedule ID: {schedule.id}\n"
                f"Frequency: Every {schedule.run_every} {schedule.unit if schedule.run_every == 1 else schedule.unit + 's'}\n"  # type: ignore
                f"Created at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            comment = Comment(
                card_id=new_card.id,
                comment=comment_text,
                order=max_comment_order + 1
            )
            db.add(comment)

            # Queue websocket broadcast for post-commit publish.
            column = db.query(BoardColumn).filter(BoardColumn.id == template.column_id).first()
            board_id = column.board_id if column else None
            if board_id is not None:
                pending_broadcasts.append({
                    'board_id': board_id,
                    'column_id': new_card.column_id,
                    'card_id': new_card.id,
                    'card_data': {
                        'id': new_card.id,
                        'column_id': new_card.column_id,
                        'title': new_card.title,
                        'description': new_card.description,
                        'order': new_card.order,
                        'scheduled': new_card.scheduled,
                        'schedule': new_card.schedule,
                        'archived': new_card.archived,
                        'done': new_card.done,
                        'done_datetime': new_card.done_datetime.isoformat() if new_card.done_datetime else None,
                        'created_at': new_card.created_at.isoformat() if new_card.created_at else None,
                        'updated_at': new_card.updated_at.isoformat() if new_card.updated_at else None
                    }
                })
            else:
                logger.warning(
                    f"Skipping scheduler card_created broadcast for card {new_card.id}: column {template.column_id} has no board_id"
                )
            
            logger.info(f"Created card {new_card.id} from schedule {schedule.id}")
            return new_card
            
        except Exception as e:
            logger.error(f"Error creating card from schedule {schedule.id}: {str(e)}")
            raise


# Global scheduler instance
_scheduler = None


def get_scheduler() -> CardScheduler:
    """Get the global card scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = CardScheduler()
    return _scheduler


def start_scheduler():
    """Start the card scheduler."""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler():
    """Stop the card scheduler."""
    scheduler = get_scheduler()
    scheduler.stop()


if __name__ == "__main__":
    # Configure logging for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info("Starting card scheduler in standalone mode")
    start_scheduler()
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
        stop_scheduler()

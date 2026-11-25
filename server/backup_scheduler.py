"""Automatic backup scheduler service."""
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import logging

from sqlalchemy import text
from database import SessionLocal
from models import Setting, Notification
from notification_utils import create_notification
from host_power import holds_host_power
from scheduler_lock import (
    acquire_scheduler_lock,
    release_scheduler_lock,
    update_scheduler_heartbeat,
)

logger = logging.getLogger(__name__)


def _get_setting_value(db, key: str, default=None):
    """Get a setting value from the database with JSON parsing.
    
    Args:
        db: Database session
        key: Setting key
        default: Default value if setting not found
        
    Returns:
        Parsed setting value or default
    """
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            return setting.value
    return default

class BackupScheduler:
    """Manages automatic database backups on a schedule."""
    
    def __init__(self):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_backup_time: Optional[datetime] = None
        self.backup_dir = Path("/app/backups")
        self.lock_file = Path("/tmp/aft_backup_scheduler.lock")
        self.permission_error = None  # Stores permission error message if directory not writable
        self.last_permission_check: Optional[datetime] = None  # Timestamp of last permission check
        self.permission_check_ttl = 30  # Cache permission check for 30 seconds
        self._last_scheduled_minute_trigger: Optional[tuple] = None  # (hour, minute) tuple to prevent re-triggering in same minute
        self._scheduler_loop_running = False  # Guard against multiple scheduler loop threads
    
    def _update_heartbeat(self):
        """Update lock file with current timestamp to prove thread is alive."""
        update_scheduler_heartbeat(self.lock_file, "backup")
    
    def _check_backup_directory_permissions(self, force_check: bool = False) -> tuple[bool, Optional[str]]:
        """Check if backup directory is writable.
        
        Args:
            force_check: If True, bypass cache and always perform check.
            
        Returns:
            Tuple of (is_writable, error_message). error_message is None if writable.
        """
        # Use cached result if within TTL and not forcing check
        now = datetime.now()
        if not force_check and self.last_permission_check is not None:
            elapsed = (now - self.last_permission_check).total_seconds()
            if elapsed < self.permission_check_ttl:
                # Return cached result
                return (self.permission_error is None, self.permission_error)
        
        # Perform actual permission check
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.backup_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
            self.last_permission_check = now
            return True, None
        except PermissionError:
            error_msg = (
                f"Backup directory '{self.backup_dir}' is not writable. "
                f"On the Docker host, run: sudo chown -R 1000:1000 ./backups && sudo chmod -R 755 ./backups"
            )
            self.last_permission_check = now
            return False, error_msg
        except Exception as e:
            error_msg = f"Error checking backup directory permissions: {str(e)}"
            self.last_permission_check = now
            return False, error_msg
        
    def start(self):
        """Start the backup scheduler thread."""
        logger.info("=== Backup Scheduler Start Attempt ===")
        logger.info(f"PID: {os.getpid()}, Container: {os.environ.get('HOSTNAME', 'unknown')}")
        
        if self.running:
            logger.warning("Backup scheduler already running in this instance")
            return
        
        if self.thread is not None and self.thread.is_alive():
            logger.warning("Backup scheduler thread already alive, not starting duplicate")
            return
        
        acquired_lock, lock_details = acquire_scheduler_lock(
            lock_file=self.lock_file,
            scheduler_type="backup",
            stale_after_seconds=300,
        )
        if not acquired_lock:
            logger.info("Backup scheduler lock acquisition skipped: %s", lock_details)
            return

        logger.info("Backup scheduler lock acquired: %s", lock_details)
        
        # Check if backup directory is writable (force check on startup)
        is_writable, error_msg = self._check_backup_directory_permissions(force_check=True)
        if not is_writable:
            logger.error(error_msg)
            self.permission_error = error_msg
            create_notification(
                subject="⚠️ Backup Scheduler Permission Error",
                message=f"Automatic backups cannot start due to permission error:\n\n{error_msg}\n\nBackups are disabled until this is resolved.",
                action_title="View Backup Settings",
                action_url="/backup-restore.html"
            )
            # Clean up lock file before returning
            if self.lock_file.exists():
                self.lock_file.unlink()
            # Don't start scheduler if we can't write backups
            return
        self.permission_error = None
        
        # Validate settings on startup
        try:
            settings = self._get_settings()
            self._validate_settings(settings)
            logger.info(f"Backup scheduler validated settings: enabled={settings.get('backup_enabled')}, "
                       f"frequency={settings.get('backup_frequency_value')} {settings.get('backup_frequency_unit')}")
        except Exception as e:
            logger.error(f"Invalid backup settings on startup: {str(e)}")
            # Disable backups if settings are invalid
            self._disable_backups_due_to_invalid_settings(str(e))
            
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Backup scheduler started")
    
    def retry_start_if_permission_fixed(self):
        """Attempt to restart scheduler if it failed due to permission errors.
        
        This method can be called periodically (e.g., from API status endpoint)
        to check if permissions have been fixed and restart the scheduler.
        """
        # Check if scheduler is actually running by checking lock file
        is_actually_running = False
        if self.lock_file.exists():
            try:
                lock_data = json.loads(self.lock_file.read_text())
                pid = lock_data.get('pid')
                container_id = lock_data.get('container_id', 'unknown')
                current_container = os.environ.get('HOSTNAME', 'unknown')
                
                # Check if same container
                if container_id == current_container:
                    try:
                        os.kill(pid, 0)
                        is_actually_running = True
                    except OSError:
                        # Process doesn't exist, lock file is stale
                        pass
            except (ValueError, FileNotFoundError, json.JSONDecodeError, KeyError):
                # Invalid lock file or file disappeared
                pass
        
        # Only retry if scheduler is not actually running
        if is_actually_running:
            logger.debug("Scheduler is already running, no retry needed")
            return False
        
        # Check if permissions are now OK
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.backup_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
            
            # Permissions are fixed! Clear error and try to start
            logger.info("Backup directory permissions have been fixed, attempting to restart scheduler")
            self.permission_error = None
            
            # Stop first to ensure clean shutdown, then start
            self.stop()
            self.start()
            return True
            
        except PermissionError as e:
            # Still have permission issues
            logger.debug(f"Permission check failed during retry: {e}")
            return False
        except Exception as e:
            # Other errors
            logger.debug(f"Unexpected error during retry permission check: {e}")
            return False
        
    def stop(self):
        """Stop the backup scheduler thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        
        # Clean up lock file
        release_scheduler_lock(self.lock_file)
        logger.info("Removed backup scheduler lock file")
        
        logger.info("Backup scheduler stopped")
        
    def _disable_backups_due_to_invalid_settings(self, error_msg: str):
        """Disable backups in database due to invalid settings."""
        db = SessionLocal()
        try:
            setting = db.query(Setting).filter(Setting.key == "backup_enabled").first()
            if setting:
                setting.value = json.dumps(False)  # type: ignore
                db.commit()
                logger.warning(f"Disabled backups due to invalid settings: {error_msg}")
                create_notification(
                    subject="⚠️ Backups Disabled - Invalid Settings",
                    message=f"Automatic backups have been disabled due to invalid configuration:\n\n{error_msg}\n\nPlease review backup settings and re-enable.",
                    action_title="View Backup Settings",
                    action_url="/backup-restore.html"
                )
        except Exception as e:
            logger.error(f"Failed to disable backups: {str(e)}")
            db.rollback()
        finally:
            db.close()
    
    def _validate_settings(self, settings: dict):
        """Validate backup settings against expected types and ranges.
        
        Raises:
            ValueError: If any setting is invalid
        """
        enabled = settings.get("backup_enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"backup_enabled must be boolean, got {type(enabled)}")
        
        freq_value = settings.get("backup_frequency_value")
        if not isinstance(freq_value, int) or not (1 <= freq_value <= 99):
            raise ValueError(f"backup_frequency_value must be integer 1-99, got {freq_value}")
        
        freq_unit = settings.get("backup_frequency_unit")
        if freq_unit not in ["minutes", "hours", "daily"]:
            raise ValueError(f"backup_frequency_unit must be minutes/hours/daily, got {freq_unit}")
        
        start_time = settings.get("backup_start_time")
        if not isinstance(start_time, str):
            raise ValueError(f"backup_start_time must be string, got {type(start_time)}")
        try:
            parts = start_time.split(":")
            if len(parts) != 2:
                raise ValueError("Invalid time format")
            hours, minutes = int(parts[0]), int(parts[1])
            if not (0 <= hours <= 23 and 0 <= minutes <= 59):
                raise ValueError("Time out of range")
        except (ValueError, AttributeError) as e:
            raise ValueError(f"backup_start_time must be HH:MM format, got {start_time}: {e}")
        
        retention = settings.get("backup_retention_count")
        if not isinstance(retention, int) or not (1 <= retention <= 100):
            raise ValueError(f"backup_retention_count must be integer 1-100, got {retention}")
    
    def _get_settings(self):
        """Retrieve backup settings from database."""
        try:
            db = SessionLocal()
            try:
                settings = {
                    "backup_enabled": _get_setting_value(db, "backup_enabled", False),
                    "backup_frequency_value": _get_setting_value(db, "backup_frequency_value", 1),
                    "backup_frequency_unit": _get_setting_value(db, "backup_frequency_unit", "daily"),
                    "backup_start_time": _get_setting_value(db, "backup_start_time", "00:00"),
                    "backup_retention_count": _get_setting_value(db, "backup_retention_count", 7),
                    "backup_minimum_free_space_mb": _get_setting_value(db, "backup_minimum_free_space_mb", 100)
                }
                return settings
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to get settings from database (database may be unavailable during restore): {e}")
            # Return default settings if database is unavailable
            return {
                "backup_enabled": False,
                "backup_frequency_value": 1,
                "backup_frequency_unit": "daily",
                "backup_start_time": "00:00",
                "backup_retention_count": 7,
                "backup_minimum_free_space_mb": 100
            }
    
    def _check_disk_space(self) -> tuple[bool, Optional[str]]:
        """Check if sufficient disk space is available for backup.
        
        Returns:
            Tuple of (is_sufficient, error_message). error_message is None if sufficient.
        """
        import shutil
        
        db = SessionLocal()
        try:
            # Get minimum required space from settings
            min_space_mb = _get_setting_value(db, "backup_minimum_free_space_mb", 100)
            
            # Get disk usage statistics for backup directory
            usage = shutil.disk_usage(self.backup_dir)
            free_space_mb = usage.free / (1024 * 1024)
            
            if free_space_mb < int(min_space_mb):  # type: ignore
                error_msg = (
                    f"Insufficient disk space for backup. "
                    f"Available: {free_space_mb:.0f} MB, Required: {min_space_mb} MB"
                )
                logger.warning(error_msg)
                return False, error_msg
            
            logger.info(f"Disk space check passed: {free_space_mb:.0f} MB available, {min_space_mb} MB required")
            return True, None
            
        except Exception as e:
            error_msg = f"Error checking disk space: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
        finally:
            db.close()
            
    def _update_last_backup_setting(self):
        """Update the last backup timestamp in settings."""
        db = SessionLocal()
        try:
            timestamp = datetime.now().isoformat()
            setting = db.query(Setting).filter(Setting.key == "backup_last_run").first()
            if setting:
                setting.value = json.dumps(timestamp)  # type: ignore
            else:
                setting = Setting(key="backup_last_run", value=json.dumps(timestamp))
                db.add(setting)
            db.commit()
            self.last_backup_time = datetime.now()
        except Exception as e:
            logger.error(f"Error updating backup timestamp: {str(e)}")
            db.rollback()
            # Still update in-memory time even if DB update fails
            self.last_backup_time = datetime.now()
        finally:
            db.close()
            
    def _parse_start_time(self, time_str: str) -> datetime:
        """Parse time string (HH:MM) and return next occurrence as datetime."""
        try:
            hour, minute = map(int, time_str.split(':'))
            now = datetime.now()
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If the time has already passed today, schedule for tomorrow
            if next_run <= now:
                next_run += timedelta(days=1)
                
            return next_run
        except (ValueError, AttributeError):
            # Default to current time if parsing fails
            return datetime.now()
            
    def _get_frequency_timedelta(self, value, unit: str) -> timedelta:
        """Convert frequency value and unit to timedelta."""
        try:
            val = int(value) if not isinstance(value, int) else value
            if unit == "minutes":
                return timedelta(minutes=val)
            elif unit == "hours":
                return timedelta(hours=val)
            elif unit == "days":
                return timedelta(days=val)
        except (ValueError, TypeError):
            # Invalid value or unit, fall through to default
            pass
        
        # Default to 24 hours
        return timedelta(hours=24)
        
    def _should_run_backup(self, settings: dict) -> bool:
        """Determine if a backup should run now.
        
        Two simple checks determine if a backup should run:
        
            Check 1 - Backup interval coverage:
            - Runs immediately if no backup exists, OR
            - Runs if last backup was more than frequency ago (catches missed/late backups)

            Check 2 - Scheduled time reached:
            - Daily: now matches start_time (HH:MM)
            - Hourly: now.minute matches start_minute, and we're at a frequency-aligned hour
            - Minute: we're at a frequency-aligned minute
        
        If both checks fail, the overdue monitor (frequency + 5 minutes) will detect
        and notify about any unexpected backup gaps.
        
        Note: Only frequencies of X minutes, X hours, or daily are supported.
        Less frequent than daily (e.g., every X days) is not supported as it's against best practice.
        """
        # Check if backups are enabled
        if not settings.get("backup_enabled"):
            return False
        
        # Validate settings before attempting backup
        try:
            self._validate_settings(settings)
        except ValueError as e:
            logger.error(f"Invalid backup settings detected: {str(e)}")
            self._disable_backups_due_to_invalid_settings(str(e))
            return False
        
        # Get frequency and start time settings
        freq_value = settings.get("backup_frequency_value", 1)
        freq_unit = settings.get("backup_frequency_unit", "daily")
        start_time = settings.get("backup_start_time", "00:00")
        
        frequency = self._get_frequency_timedelta(freq_value, freq_unit)
        now = datetime.now()
        
        # Load last backup time from class or database if not set
        if not self.last_backup_time:
            db = SessionLocal()
            try:
                last_run = _get_setting_value(db, "backup_last_run")
                if last_run:  # type: ignore
                    try:
                        self.last_backup_time = datetime.fromisoformat(str(last_run))  # type: ignore
                    except ValueError:
                        pass
            finally:
                db.close()
        
        # Check 1: Has enough time passed since last backup? (or no previous backup exists)
        if not self.last_backup_time:
            logger.info("No previous backup found, running immediately")
            return True
        
        time_since_last = now - self.last_backup_time
        if time_since_last >= frequency:
            logger.info(f"Backup interval coverage check: last backup was {time_since_last} ago (>= {frequency}), running backup")
            return True
        
        # Additional deduplication: even if interval coverage check passes,
        # skip if we ran a backup in the last 60 seconds (covers all scheduled time windows)
        # Use <= to catch exact 60-second boundaries due to processing delays
        if time_since_last <= timedelta(seconds=60):
            logger.debug(f"Backup ran {time_since_last.total_seconds():.0f}s ago, skipping to prevent duplicates within same minute window")
            return False
        
        # Check 2: Is this a scheduled backup time?
        try:
            start_hour, start_minute = map(int, start_time.split(':'))
        except (ValueError, AttributeError):
            # Invalid start_time, skip scheduled check
            logger.warning(f"Invalid start_time format: {start_time}, skipping scheduled time check")
            return False
        
        if freq_unit == "daily":
            # Daily backup: check if we're at the scheduled time
            # Use second-level granularity to prevent multiple backups in the same minute
            if now.hour == start_hour and now.minute == start_minute and now.second < 60:
                # Only run if we haven't run in the last 60 seconds (covers entire minute window)
                if self.last_backup_time and (now - self.last_backup_time).total_seconds() < 60:
                    logger.debug(f"Scheduled daily time reached but backup ran {(now - self.last_backup_time).total_seconds():.0f}s ago, skipping")
                    return False
                logger.info(f"Scheduled daily backup time reached: {start_time}")
                return True
        
        elif freq_unit == "hours":
            # Hourly backup: check if we're at the scheduled minute and at a frequency-aligned hour
            if now.minute == start_minute:
                # Calculate hours since midnight
                hours_since_midnight = now.hour
                # Check if we're at a frequency-aligned hour (e.g., every 6 hours means 0, 6, 12, 18)
                if hours_since_midnight % freq_value == 0:
                    # Only run if we haven't run in the last 60 seconds (covers entire minute window)
                    if self.last_backup_time and (now - self.last_backup_time).total_seconds() < 60:
                        logger.debug(f"Scheduled hourly time reached but backup ran {(now - self.last_backup_time).total_seconds():.0f}s ago, skipping")
                        return False
                    logger.info(f"Scheduled hourly backup time reached: every {freq_value} hours at :{start_minute:02d}")
                    return True
        
        elif freq_unit == "minutes":
            # Minute backup: check if we're at a frequency-aligned minute
            # Calculate minutes since midnight
            minutes_since_midnight = now.hour * 60 + now.minute
            # Check if we're at a frequency-aligned minute
            if minutes_since_midnight % freq_value == 0:
                # Additional deduplication: only run if we haven't run in the last 60 seconds
                # Use <= to catch exact 60-second boundaries due to processing delays
                if self.last_backup_time and (now - self.last_backup_time).total_seconds() <= 60:
                    logger.debug(f"Scheduled minute time reached but backup ran {(now - self.last_backup_time).total_seconds():.0f}s ago, skipping")
                    return False
                # Use second-precision: only trigger once per minute window
                # Store the last scheduled trigger time (rounded to minute) to prevent re-triggering within same minute
                if not hasattr(self, '_last_scheduled_minute_trigger'):
                    self._last_scheduled_minute_trigger = None
                
                current_minute_key = (now.hour, now.minute)
                if self._last_scheduled_minute_trigger == current_minute_key:
                    logger.debug(f"Already triggered backup for minute {now.hour:02d}:{now.minute:02d}, skipping")
                    return False
                
                self._last_scheduled_minute_trigger = current_minute_key
                logger.info(f"Scheduled minute backup time reached: every {freq_value} minutes")
                return True
        
        # Not time yet
        logger.debug("Not scheduled time yet for backup, waiting")
        return False
        
    def _check_and_notify_overdue(self, settings: dict):
        """Check if backup is overdue and send notification if needed.
        
        A backup is considered OVERDUE (and requires user attention) if it's more than
        frequency + 5 minutes since last backup. This gives the scheduler at least
        4 passes (5 minutes / 60 second interval) to attempt the backup.
        
        This is separate from the normal scheduling: a backup can be on-schedule but
        still appear "missed" in the UI if it's overdue. The overdue check helps
        detect when:
        - Scheduler crashed or is stuck
        - Previous backup failed silently
        - Backups were disabled for too long then re-enabled
        
        Won't flag as overdue if backups were just turned on after being offline
        since the check happens after the backup attempt.
        
        Checks database for existing unread overdue notifications to prevent
        duplicates across process restarts.
        """
        db = SessionLocal()
        try:
            latest_backup = self._get_latest_backup_info()
            latest_backup_date = latest_backup.get("date")
            
            if not latest_backup_date:
                # No backup exists at all - don't spam notifications on first run
                return
            
            freq_value = settings.get("backup_frequency_value", 1)
            freq_unit = settings.get("backup_frequency_unit", "daily")
            
            # Calculate frequency in timedelta
            if freq_unit == "minutes":
                frequency = timedelta(minutes=freq_value)
            elif freq_unit == "hours":
                frequency = timedelta(hours=freq_value)
            else:  # days
                frequency = timedelta(days=freq_value)
            
            now = datetime.now()
            time_since_last = now - latest_backup_date
            
            # Overdue threshold is frequency + 5 minutes
            # This gives scheduler 4+ passes (5 min / 60 sec) to attempt the backup
            overdue_threshold = frequency + timedelta(minutes=5)
            
            # If overdue by more than the threshold, send notification
            if time_since_last > overdue_threshold:
                # Check if an unread overdue notification already exists
                existing_notification = db.query(Notification).filter(
                    Notification.subject.like("%Backup Overdue%"),
                    Notification.unread.is_(True)
                ).first()
                
                if not existing_notification:
                    overdue_by = time_since_last - frequency
                    create_notification(
                        subject="⚠️ Backup Overdue",
                        message=f"Automatic backups are overdue by {self._format_timedelta(overdue_by)}.\n\nLast backup: {latest_backup_date.strftime('%Y-%m-%d %H:%M:%S')}\nExpected frequency: {freq_value} {freq_unit}\n\nCheck backup scheduler status and logs for issues.",
                        action_title="View Backup Settings",
                        action_url="/backup-restore.html"
                    )
                    logger.warning(f"Backup is overdue by {overdue_by}, notification sent")
            else:
                # Backup is within acceptable window - no action needed
                # Users will manually dismiss overdue notifications when they see them
                pass
                
        except Exception as e:
            logger.error(f"Error checking for overdue backup: {str(e)}")
        finally:
            db.close()
    
    def _format_timedelta(self, td: timedelta) -> str:
        """Format a timedelta into a human-readable string."""
        total_seconds = int(td.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        return ", ".join(parts) if parts else "less than a minute"
        
    @holds_host_power('backup')
    def _create_backup(self):
        """Create a database backup file."""
        try:
            # Ensure backup directory exists
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if sufficient disk space is available
            has_space, space_error = self._check_disk_space()
            if not has_space:
                logger.error(f"Backup skipped: {space_error}")
                create_notification(
                    subject="❌ Backup Failed - Insufficient Disk Space",
                    message=f"Automatic backup could not run due to insufficient free disk space.\n\n{space_error}\n\nPlease free up disk space or adjust the minimum free space requirement in backup settings.",
                    action_title="View Backup Settings",
                    action_url="/backup-restore.html"
                )
                return
            
            # Get current Alembic version
            db = SessionLocal()
            try:
                result = db.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                db_version = row[0] if row else "unknown"
            finally:
                db.close()
            
            # Get database credentials
            db_user = os.environ.get("MYSQL_USER")
            db_password = os.environ.get("MYSQL_PASSWORD")
            db_name = os.environ.get("MYSQL_DATABASE")
            db_host = "db"
            
            # Create backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"auto_backup_{timestamp}.sql"
            backup_path = self.backup_dir / backup_filename
            
            # Write version header
            with open(backup_path, "w") as f:
                f.write("-- AFT Automatic Database Backup\n")
                f.write(f"-- Alembic Version: {db_version}\n")
                f.write(f"-- Backup Date: {datetime.now().isoformat()}\n")
                f.write("--\n\n")
            
            # Run mysqldump
            mysqldump_cmd = [
                "mysqldump",
                "-h", db_host,
                "-u", db_user,
                f"-p{db_password}",
                "--single-transaction",
                "--routines",
                "--triggers",
                "--skip-ssl",
                db_name,
            ]
            
            with open(backup_path, "a") as f:
                result = subprocess.run(
                    mysqldump_cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True
                )
            
            if result.returncode != 0:
                backup_path.unlink(missing_ok=True)
                error_msg = f"mysqldump failed: {result.stderr}"
                create_notification(
                    subject="⚠️ Automatic Backup Failed",
                    message=f"Scheduled automatic backup failed:\n\n{error_msg}\n\nCheck database connection and mysqldump availability in server logs.",
                    action_title="View Backup Settings",
                    action_url="/backup-restore.html"
                )
                raise Exception(error_msg)
            
            logger.info(f"Automatic backup created: {backup_filename}")
            
            # Create resolution notification if there's an unread overdue notification
            # Use a new session to check notifications
            notification_db = SessionLocal()
            try:
                existing_overdue = notification_db.query(Notification).filter(
                    Notification.subject.like("%Backup Overdue%"),
                    Notification.unread.is_(True)
                ).first()
                
                if existing_overdue:
                    # Mark the overdue notification as read to prevent duplicate resolution messages
                    existing_overdue.unread = False  # type: ignore
                    try:
                        notification_db.commit()
                    except Exception as e:
                        logger.error(f"Error marking overdue notification as read: {str(e)}")
                        notification_db.rollback()
                    create_notification(
                        subject="✅ Backup Completed",
                        message=f"Automatic backup completed successfully after being overdue.\n\nBackup: {backup_filename}\nCreated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nBackups are now on schedule.",
                        action_title="View Backups",
                        action_url="/backup-restore.html"
                    )
            finally:
                notification_db.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Error creating automatic backup: {str(e)}")
            create_notification(
                subject="⚠️ Automatic Backup Error",
                message=f"Failed to create scheduled backup:\n\n{str(e)}\n\nCheck server logs for details. Backups will retry on next schedule.",
                action_title="View Backup Settings",
                action_url="/backup-restore.html"
            )
            return False
            
    def _rotate_backups(self, retention_count: int):
        """Remove old backups to maintain retention count."""
        try:
            # Get all auto backup files sorted by modification time
            backup_files = sorted(
                self.backup_dir.glob("auto_backup_*.sql"),
                key=lambda p: p.stat().st_mtime,
                reverse=True  # Newest first
            )
            
            # Remove old backups beyond retention count
            for backup_file in backup_files[retention_count:]:
                backup_file.unlink()
                logger.info(f"Rotated old backup: {backup_file.name}")
                
        except Exception as e:
            logger.error(f"Error rotating backups: {str(e)}")
            
    def _run_scheduler(self):
        """Main scheduler loop."""
        logger.info("Backup scheduler loop started")
        
        # Guard against multiple scheduler threads in same instance
        if hasattr(self, '_scheduler_loop_running') and self._scheduler_loop_running:
            logger.error("Scheduler loop already running! Multiple threads detected, aborting")
            return
        
        self._scheduler_loop_running = True
        
        while self.running:
            logger.info("Backup scheduler loop iteration starting")
            try:
                # Update heartbeat to prove we're alive
                self._update_heartbeat()
                
                # Recheck permissions periodically to detect if they've been fixed or broken (force check)
                is_writable, error_msg = self._check_backup_directory_permissions(force_check=True)
                if not is_writable:
                    if self.permission_error != error_msg:
                        logger.error(error_msg)
                        # Create notification when permission error first detected or changes
                        create_notification(
                            subject="⚠️ Backup Permission Error",
                            message=f"Automatic backups cannot run due to permission error:\n\n{error_msg}\n\nBackups are paused until this is resolved.",
                            action_title="View Backup Settings",
                            action_url="/backup-restore.html"
                        )
                    self.permission_error = error_msg
                    # Skip backup if we can't write
                    time.sleep(60)
                    continue
                
                # Permissions are OK, clear any previous error
                if self.permission_error is not None:
                    logger.info("Backup directory permissions have been fixed")
                    create_notification(
                        subject="✅ Backup Permissions Restored",
                        message="Backup directory permissions have been fixed. Automatic backups will resume on schedule.",
                        action_title="View Backup Settings",
                        action_url="/backup-restore.html"
                    )
                self.permission_error = None
                
                settings = self._get_settings()
                
                should_run = self._should_run_backup(settings)
                logger.info(f"Backup check: should_run={should_run}, enabled={settings.get('backup_enabled')}, last_backup={self.last_backup_time}")
                
                # Attempt to run backup if scheduled
                if should_run:
                    logger.info("Running scheduled backup")
                    
                    if self._create_backup():
                        # Update in-memory last_backup_time IMMEDIATELY to prevent race conditions
                        # This prevents another scheduler iteration from creating a duplicate backup
                        # before the database update completes
                        self.last_backup_time = datetime.now()
                        
                        # Also persist to database (non-critical if fails, in-memory timestamp prevents duplicates)
                        self._update_last_backup_setting()
                        
                        # Rotate old backups
                        try:
                            retention = settings.get("backup_retention_count", 7)
                            if not isinstance(retention, int):
                                retention = int(retention)
                            self._rotate_backups(retention)
                        except (ValueError, TypeError):
                            logger.warning("Invalid retention count, skipping rotation")
                
                # Check if backup is overdue AFTER attempting to run
                # This avoids race condition and also detects overdue status even if backups are minute-frequency
                # (scheduler runs every 60 seconds, so minute-frequency backups would never be checked otherwise)
                if settings.get('backup_enabled'):
                    self._check_and_notify_overdue(settings)
                
                # Sleep for 1 minute before next check
                time.sleep(60)
                
            except Exception as e:
                import traceback
                logger.error(f"Error in backup scheduler loop: {str(e)}\n{traceback.format_exc()}")
                time.sleep(60)  # Sleep before retrying
                
        self._scheduler_loop_running = False
        logger.info("Backup scheduler loop stopped")
        
    def get_status(self) -> dict:
        """Get current scheduler status."""
        settings = self._get_settings()
        
        enabled = settings.get("backup_enabled", False)
        freq_value = settings.get("backup_frequency_value", 1)
        freq_unit = settings.get("backup_frequency_unit", "daily")
        retention = settings.get("backup_retention_count", 7)
        
        # Check permissions with caching (uses TTL to avoid expensive file ops on frequent polling)
        is_writable, error_msg = self._check_backup_directory_permissions(force_check=False)
        if not is_writable:
            if self.permission_error != error_msg:
                logger.error(error_msg)
            self.permission_error = error_msg
        else:
            # Permissions are OK, clear any previous error
            if self.permission_error is not None:
                logger.info("Backup directory permissions are now OK, clearing error")
            self.permission_error = None
        
        # Check if scheduler is actually running by checking lock file
        is_running = False
        if self.lock_file.exists():
            try:
                lock_data = json.loads(self.lock_file.read_text())
                pid = lock_data.get('pid')
                container_id = lock_data.get('container_id', 'unknown')
                current_container = os.environ.get('HOSTNAME', 'unknown')
                
                logger.info(f"Lock file exists with PID {pid}, container {container_id}, checking if process is alive")
                
                # Check if same container
                if container_id != current_container:
                    logger.warning(f"Lock file from different container: {container_id} vs {current_container}")
                    is_running = False
                else:
                    try:
                        os.kill(pid, 0)  # Check if process exists
                        is_running = True
                        logger.info(f"Process {pid} is alive, scheduler is running")
                    except OSError as e:
                        # Process doesn't exist
                        logger.warning(f"Process {pid} not found (errno {e.errno}), scheduler not running")
                        is_running = False
            except (ValueError, FileNotFoundError, json.JSONDecodeError, KeyError) as e:
                logger.error(f"Error reading lock file: {str(e)}")
                is_running = False
        else:
            logger.info("Lock file does not exist, scheduler not running")
        
        # Get latest backup file info
        latest_backup = self._get_latest_backup_info()
        latest_backup_path = latest_backup.get("path")
        latest_backup_date = latest_backup.get("date")
        
        # Check if backup is within expected window
        within_window = False
        if latest_backup_date and enabled:
            within_window = self._is_backup_within_window(
                latest_backup_date, 
                freq_value, 
                freq_unit
            )
        
        return {
            "running": is_running,
            "enabled": enabled,
            "last_backup": self.last_backup_time.isoformat() if self.last_backup_time else None,
            "frequency": f"{freq_value} {freq_unit}",
            "retention_count": retention,
            "start_time": settings.get("backup_start_time", "00:00"),
            "latest_backup_file": latest_backup_path,
            "latest_backup_date": latest_backup_date.isoformat() if latest_backup_date else None,
            "backup_within_window": within_window,
            "permission_error": self.permission_error
        }
    
    def _get_latest_backup_info(self) -> dict:
        """Get information about the latest backup file.
        
        Returns:
            dict: Contains 'path' (filename or None) and 'date' (datetime or None)
        """
        try:
            if not self.backup_dir.exists():
                return {"path": None, "date": None}
            
            # Find all .sql files in backup directory
            backup_files = list(self.backup_dir.glob("auto_backup_*.sql"))
            
            if not backup_files:
                return {"path": None, "date": None}
            
            # Get the most recent file by creation time
            latest_file = max(backup_files, key=lambda f: f.stat().st_ctime)
            latest_date = datetime.fromtimestamp(latest_file.stat().st_ctime)
            
            return {
                "path": latest_file.name,
                "date": latest_date
            }
        except Exception as e:
            logger.error(f"Error getting latest backup info: {str(e)}")
            return {"path": None, "date": None}
    
    def _is_backup_within_window(self, backup_date: datetime, freq_value: int, freq_unit: str) -> bool:
        """Check if backup is within the expected backup window.
        
        This uses the same threshold as the overdue monitor (frequency + 5 minutes)
        for consistency. Backups within this window are considered healthy in the
        status widget.
        
        Args:
            backup_date: Date of the backup file
            freq_value: Frequency value (e.g., 5, 24, 7)
            freq_unit: Frequency unit ('minutes', 'hours', 'daily')
            
        Returns:
            bool: True if backup is within expected window, False otherwise
        """
        now = datetime.now()
        
        # Calculate window (frequency + 5 minutes for status reporting)
        # This matches the overdue threshold used for notifications
        if freq_unit == "minutes":
            window = timedelta(minutes=freq_value) + timedelta(minutes=5)
        elif freq_unit == "hours":
            window = timedelta(hours=freq_value) + timedelta(minutes=5)
        elif freq_unit == "daily":
            window = timedelta(days=freq_value) + timedelta(minutes=5)
        else:
            # Unknown unit, assume not within window
            return False
        
        time_since_backup = now - backup_date
        return time_since_backup <= window



# Global scheduler instance
_scheduler = None
_scheduler_lock = threading.Lock()

def get_scheduler() -> BackupScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = BackupScheduler()
    return _scheduler

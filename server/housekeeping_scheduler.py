"""Housekeeping scheduler service for periodic maintenance tasks."""
import threading
import time
import logging
import requests
import json
import os
import tempfile
from datetime import datetime
from typing import Optional
from pathlib import Path
from packaging import version

from notification_utils import create_notification
from scheduler_lock import (
    acquire_scheduler_lock,
    release_scheduler_lock,
    update_scheduler_heartbeat,
)

logger = logging.getLogger(__name__)

# GitHub API configuration
GITHUB_REPO_OWNER = "sjefferson99"
GITHUB_REPO_NAME = "aft"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"


class HousekeepingScheduler:
    """Manages periodic housekeeping tasks."""
    
    def __init__(self, app_version: str):
        from datetime import datetime
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock_file = Path(tempfile.gettempdir()) / "aft_housekeeping_scheduler.lock"
        self.app_version = app_version
        self.check_interval = 60  # Thread runs every 60 seconds to update heartbeat
        
        # Track last run times for individual tasks
        self.last_version_check = None  # Last time version was checked
        self.version_check_interval = 3600  # Check for updates every hour
        
        # Track scheduler health states for notifications
        self.scheduler_health_states: dict = {
            'backup_scheduler': True,
            'card_scheduler': True,
            'housekeeping_scheduler': True
        }
        self.last_health_notification: dict = {
            'backup_scheduler': None,
            'card_scheduler': None,
            'housekeeping_scheduler': None
        }
        self.health_notification_cooldown = 1800  # 30 minutes between notifications
        self.startup_time = datetime.now()  # Track when scheduler started
        self.startup_grace_period = 120  # Wait 2 minutes after startup before checking health
    
    def _update_heartbeat(self):
        """Update lock file with current timestamp to prove thread is alive."""
        update_scheduler_heartbeat(self.lock_file, "housekeeping")
    
    def start(self):
        """Start the housekeeping scheduler thread."""
        logger.info("=== Housekeeping Scheduler Start Attempt ===")
        logger.info(f"PID: {os.getpid()}, Container: {os.environ.get('HOSTNAME', 'unknown')}")
        
        if self.running:
            logger.warning("Housekeeping scheduler already running in this instance")
            return
        
        acquired_lock, lock_details = acquire_scheduler_lock(
            lock_file=self.lock_file,
            scheduler_type="housekeeping",
            stale_after_seconds=300,
        )
        if not acquired_lock:
            logger.info("Housekeeping scheduler lock acquisition skipped: %s", lock_details)
            return

        logger.info("Housekeeping scheduler lock acquired: %s", lock_details)
        
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info(f"✓ Housekeeping scheduler started successfully - PID: {os.getpid()}, Thread ID: {self.thread.ident}")
    
    def stop(self):
        """Stop the housekeeping scheduler thread."""
        if not self.running:
            return
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        
        # Remove lock file
        release_scheduler_lock(self.lock_file)
        
        logger.info("Housekeeping scheduler stopped")
    
    def _run_scheduler(self):
        """Main scheduler loop - runs every 60 seconds."""
        logger.info("Housekeeping scheduler thread started")
        
        while self.running:
            try:
                # Update heartbeat every loop iteration to prove we're alive
                self._update_heartbeat()
                
                # Check if housekeeping is enabled
                if self._is_enabled():
                    # Run version check if enough time has passed
                    self._run_version_check_if_needed()
                    
                    # Check health of other schedulers and create notifications if needed
                    self._check_scheduler_health()
                    
                    # Future tasks can be added here with similar patterns:
                    # self._run_cleanup_if_needed()
                    # self._run_backup_rotation_if_needed()
                else:
                    logger.debug("Housekeeping scheduler is disabled, skipping checks")
                
                # Sleep for 60 seconds before next heartbeat update
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in housekeeping scheduler loop: {e}", exc_info=True)
                time.sleep(60)
    
    def _run_version_check_if_needed(self):
        """Run version check only if enough time has passed since last check."""
        from datetime import datetime
        
        now = datetime.now()
        
        # Check if we should run version check
        if self.last_version_check is None:
            # First run
            should_check = True
        else:
            time_since_last_check = (now - self.last_version_check).total_seconds()
            should_check = time_since_last_check >= self.version_check_interval
        
        if should_check:
            logger.info(f"Running version check (last check: {self.last_version_check})")
            self._check_for_updates()
            self.last_version_check = now
        else:
            time_since_last = (now - self.last_version_check).total_seconds()
            logger.debug(f"Skipping version check ({int(time_since_last)}s since last check, need {self.version_check_interval}s)")
    
    def _check_scheduler_health(self):
        """Check health of all schedulers and create notifications if unhealthy."""
        from datetime import datetime
        
        # Skip health checks during startup grace period
        time_since_startup = (datetime.now() - self.startup_time).total_seconds()
        if time_since_startup < self.startup_grace_period:
            logger.debug(f"Skipping health check during startup grace period ({int(time_since_startup)}s / {self.startup_grace_period}s)")
            return
        
        temp_dir = Path(tempfile.gettempdir())
        schedulers_to_check = [
            ('backup_scheduler', temp_dir / 'aft_backup_scheduler.lock', 'Backup Scheduler'),
            ('card_scheduler', temp_dir / 'aft_card_scheduler.lock', 'Card Scheduler'),
        ]
        
        for scheduler_key, lock_file, display_name in schedulers_to_check:
            try:
                is_healthy = self._is_scheduler_healthy(lock_file)
                self._handle_scheduler_health_change(scheduler_key, display_name, is_healthy)
            except Exception as e:
                logger.error(f"Error checking {display_name} health: {e}")
    
    def _is_scheduler_healthy(self, lock_file: Path) -> bool:
        """Check if a scheduler is healthy based on its lock file.
        
        Args:
            lock_file: Path to the scheduler's lock file
            
        Returns:
            True if healthy, False otherwise
        """
        if not lock_file.exists():
            return False
        
        try:
            from datetime import datetime
            lock_data = json.loads(lock_file.read_text())
            last_heartbeat = datetime.fromisoformat(lock_data['last_heartbeat'])
            lock_age = (datetime.now() - last_heartbeat).total_seconds()
            
            # Consider healthy if heartbeat is less than 2.5 minutes old (2.5x the 60s loop interval)
            return lock_age < 150
        except Exception as e:
            logger.warning(f"Error reading lock file {lock_file}: {e}")
            return False
    
    def _handle_scheduler_health_change(self, scheduler_key: str, display_name: str, is_healthy: bool):
        """Handle state changes and create notifications when scheduler becomes unhealthy.
        
        Args:
            scheduler_key: Internal key for the scheduler
            display_name: User-facing name for the scheduler
            is_healthy: Current health status
        """
        from datetime import datetime
        
        previous_state = self.scheduler_health_states.get(scheduler_key, True)
        
        # State changed from healthy to unhealthy
        if previous_state and not is_healthy:
            # Check cooldown to avoid notification spam
            last_notified = self.last_health_notification.get(scheduler_key)
            should_notify = True
            
            if last_notified:
                time_since_last = (datetime.now() - last_notified).total_seconds()
                should_notify = time_since_last >= self.health_notification_cooldown
            
            if should_notify:
                logger.warning(f"{display_name} has become unhealthy")
                create_notification(
                    subject=f"⚠️ {display_name} Unhealthy",
                    message=f"The {display_name} service has stopped responding.\n\n"
                            f"The scheduler's heartbeat has not updated in over 2 minutes. "
                            f"This may indicate the service has crashed or is stuck.\n\n"
                            f"Check the system information page for details.",
                    action_title="View System Status",
                    action_url="/system-info.html"
                )
                self.last_health_notification[scheduler_key] = datetime.now()
        
        # State changed from unhealthy to healthy
        elif not previous_state and is_healthy:
            logger.info(f"{display_name} recovered and is now healthy")
        
        # Update tracked state
        self.scheduler_health_states[scheduler_key] = is_healthy
    
    def _is_enabled(self) -> bool:
        """Check if housekeeping scheduler is enabled in settings."""
        try:
            from database import SessionLocal
            from models import Setting
            
            db = SessionLocal()
            try:
                setting = db.query(Setting).filter(Setting.key == "housekeeping_enabled").first()
                if setting is not None and setting.value is not None:
                    return json.loads(str(setting.value))
                return True  # Default to enabled
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error checking housekeeping_enabled setting: {e}")
            return True  # Default to enabled on error
    
    def _check_for_updates(self):
        """Check GitHub for new releases and create notification if update available."""
        try:
            # Fetch latest release from GitHub
            response = requests.get(GITHUB_API_URL, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"Failed to check for updates: HTTP {response.status_code}")
                return
            
            data = response.json()
            latest_version = data.get('tag_name', '').lstrip('v')
            release_url = data.get('html_url', f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases")
            
            if not latest_version:
                logger.warning("No version information in GitHub release")
                return
            
            # Parse versions for comparison
            try:
                current_ver = version.parse(self.app_version)
                latest_ver = version.parse(latest_version)
            except Exception as e:
                logger.error(f"Error parsing version numbers: {e}")
                return
            
            # Compare versions
            if latest_ver > current_ver:
                # New version available - check if we should notify
                logger.info(f"New version available: {latest_version} (current: {self.app_version})")
                
                # Check if a notification already exists, read or unread
                if self._has_version_notification(latest_version):
                    logger.debug(f"Notification already exists for version {latest_version}")
                    return
                
                # Create notification
                subject = f"New Version Available: {latest_version}"
                message = (
                    f"A new version of AFT ({latest_version}) is available. "
                    f"You are currently running version {self.app_version}. "
                    f"Click the button below to view the release notes and download."
                )
                action_title = "View Release"
                action_url = release_url
                
                success = create_notification(
                    subject=subject,
                    message=message,
                    action_title=action_title,
                    action_url=action_url
                )
                
                if success:
                    logger.info(f"Created notification for new version {latest_version}")
                else:
                    logger.error("Failed to create notification for new version")
            
            elif latest_ver == current_ver:
                logger.debug(f"Already running latest version: {self.app_version}")
            else:
                # Current version is newer (development/testing branch)
                logger.debug(f"Running development version {self.app_version} (latest release: {latest_version})")
        
        except requests.RequestException as e:
            logger.warning(f"Network error checking for updates: {e}")
        except Exception as e:
            logger.error(f"Unexpected error checking for updates: {e}", exc_info=True)
    
    def _has_version_notification(self, new_version: str) -> bool:
        """Check if a notification already exists for this version.
        
        Returns True if a notification exists, read or unread, False otherwise.
        """
        try:
            from models import Notification
            from database import SessionLocal
            
            # Look for notifications with this version in the subject
            subject_pattern = f"New Version Available: {new_version}"
            
            session = SessionLocal()
            try:
                existing = session.query(Notification).filter(
                    Notification.subject == subject_pattern
                ).first()
                
                return existing is not None
            finally:
                session.close()
            
        except Exception as e:
            logger.error(f"Error checking for existing notifications: {e}")
            # On error, assume notification doesn't exist to avoid missing updates
            return False
    
    def get_status(self) -> dict:
        """Get current scheduler status."""
        from database import SessionLocal
        from models import Setting
        import psutil
        
        # Get enabled setting from database
        db = SessionLocal()
        try:
            setting = db.query(Setting).filter(Setting.key == "housekeeping_enabled").first()
            if setting is not None and setting.value is not None:
                enabled = json.loads(str(setting.value))
            else:
                enabled = True
        except Exception as e:
            logger.error(f"Error reading housekeeping_enabled setting: {e}")
            enabled = True  # Default to enabled
        finally:
            db.close()
        
        # Check if scheduler is actually running
        is_running = False
        if self.lock_file.exists():
            try:
                lock_data = json.loads(self.lock_file.read_text())
                pid = lock_data.get('pid')
                container_id = lock_data.get('container_id', 'unknown')
                current_container = os.environ.get('HOSTNAME', 'unknown')
                
                # Check if same container
                if container_id == current_container:
                    try:
                        is_running = psutil.pid_exists(pid)
                    except Exception:
                        is_running = False
            except (ValueError, FileNotFoundError, json.JSONDecodeError, KeyError):
                is_running = False
        
        return {
            "running": is_running,
            "enabled": enabled,
            "check_interval": self.check_interval,
            "app_version": self.app_version
        }


# Global scheduler instance
_housekeeping_scheduler: Optional[HousekeepingScheduler] = None


def get_housekeeping_scheduler(app_version: str) -> HousekeepingScheduler:
    """Get or create the housekeeping scheduler instance."""
    global _housekeeping_scheduler
    if _housekeeping_scheduler is None:
        _housekeeping_scheduler = HousekeepingScheduler(app_version)
    return _housekeeping_scheduler


def start_housekeeping_scheduler(app_version: str):
    """Start the housekeeping scheduler."""
    scheduler = get_housekeeping_scheduler(app_version)
    scheduler.start()


def stop_housekeeping_scheduler():
    """Stop the housekeeping scheduler."""
    global _housekeeping_scheduler
    if _housekeeping_scheduler:
        _housekeeping_scheduler.stop()

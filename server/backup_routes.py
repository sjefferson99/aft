from flask import Blueprint, jsonify, request, send_file, g
import subprocess
import os
import re
import tempfile
import time
import traceback
import logging
from datetime import datetime
from pathlib import Path
from database import SessionLocal, engine
from models import User
from sqlalchemy import text
from utils import require_permission
from security_validators import (
    validate_backup_file_security,
    validate_backup_file_size,
    validate_schema_integrity,
)
from notification_utils import create_notification as create_notification_internal
from restore_progress import (
    RESTORE_PROGRESS_HEADER,
    RestoreProgress,
    claim_setup_restore,
    is_valid_progress_id,
    read_progress,
    release_setup_restore,
)

logger = logging.getLogger(__name__)

backup_bp = Blueprint("backup", __name__)

# Maximum backup file size for validation (MB) - actual content size limit
MAX_BACKUP_FILE_SIZE_MB = 100

# mysqldump writes this comment above each table in a backup
TABLE_COMMENT_PATTERN = re.compile(rb'^-- Table structure for table `([A-Za-z0-9_]{1,64})`')

# Populated by configure_backup_routes()
_APP_VERSION = "unknown"


def configure_backup_routes(app_version):
    """Inject runtime configuration that is only known after app init."""
    global _APP_VERSION
    _APP_VERSION = app_version


# ---------------------------------------------------------------------------
# Helper: database creation with retry
# ---------------------------------------------------------------------------

def create_database_with_retry(db_host, db_root_password, db_name, max_retries=5, retry_delay_seconds=2):
    """Create database with retry for transient MySQL schema-directory race conditions.

    MySQL 9 can transiently report ERROR 3678 (schema directory already exists)
    immediately after a DROP DATABASE while filesystem cleanup is still settling.
    """
    create_db_cmd = [
        "mysql",
        f"-h{db_host}",
        "-uroot",
        f"-p{db_root_password}",
        "--skip-ssl",
        "-e",
        f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    ]

    last_stderr = ""
    for attempt in range(1, max_retries + 1):
        try:
            result = subprocess.run(create_db_cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise Exception("Timeout while creating database")

        if result.returncode == 0:
            logger.info(f"Database {db_name} created successfully")
            return

        stderr = (result.stderr or "").strip()
        last_stderr = stderr
        is_schema_directory_race = (
            "ERROR 3678" in stderr
            and "Schema directory" in stderr
            and "already exists" in stderr
        )

        if is_schema_directory_race and attempt < max_retries:
            logger.warning(
                f"Database create attempt {attempt}/{max_retries} hit MySQL schema directory race; "
                f"retrying in {retry_delay_seconds}s"
            )
            time.sleep(retry_delay_seconds)
            continue

        logger.error(f"Failed to create database: {stderr}")
        raise Exception(f"Failed to create database: {stderr}")

    logger.error(f"Failed to create database after {max_retries} attempts: {last_stderr}")
    raise Exception(f"Failed to create database after {max_retries} attempts: {last_stderr}")


# ---------------------------------------------------------------------------
# Helper: clearing the database
# ---------------------------------------------------------------------------

def clear_database():
    """Drop and recreate the database, leaving it empty with no schema."""
    # Get database credentials
    db_user = os.environ.get("MYSQL_USER")
    db_password = os.environ.get("MYSQL_PASSWORD")
    db_name = os.environ.get("MYSQL_DATABASE")
    db_host = "db"

    # Close any existing database sessions in this request context to avoid connection issues
    logger.info(f"Step 6.0: Closing request database sessions before killing connections")
    request_db = g.pop('db', None)
    if request_db:
        try:
            request_db.close()
            logger.info(f"Closed request database session")
        except Exception as e:
            logger.warning(f"Error closing request database session: {e}")

    # Dispose of SQLAlchemy engine connection pool so it creates fresh connections
    try:
        engine.dispose()
        logger.info(f"Disposed SQLAlchemy engine connection pool")
    except Exception as e:
        logger.warning(f"Error disposing engine pool: {e}")

    # Kill all other database connections first to release locks
    logger.info(f"Step 6.0.1: Killing all other database connections to release locks")
    get_pids_cmd = [
        "mysql",
        f"-h{db_host}",
        f"-u{db_user}",
        f"-p{db_password}",
        "--skip-ssl",
        "-N",
        "-e",
        f"SELECT id FROM INFORMATION_SCHEMA.PROCESSLIST WHERE db = '{db_name}' AND id != CONNECTION_ID();"
    ]

    try:
        result = subprocess.run(get_pids_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            pids = [pid.strip() for pid in result.stdout.strip().split('\n') if pid.strip()]
            logger.info(f"Found {len(pids)} active connections to kill: {pids}")

            for pid in pids:
                logger.info(f"Killing connection: {pid}")
                kill_cmd = [
                    "mysql",
                    f"-h{db_host}",
                    f"-u{db_user}",
                    f"-p{db_password}",
                    "--skip-ssl",
                    "-e",
                    f"KILL {pid};"
                ]
                try:
                    subprocess.run(kill_cmd, capture_output=True, text=True, timeout=5)
                    logger.info(f"Killed connection: {pid}")
                except Exception as e:
                    logger.warning(f"Could not kill connection {pid}: {e}")

            logger.info(f"Step 6.0.2: Waiting 2 seconds for connections to terminate")
            time.sleep(2)
        else:
            logger.info(f"No active connections to kill")
    except Exception as e:
        logger.warning(f"Error killing connections: {e}")

    # Use DROP DATABASE / CREATE DATABASE for a completely clean slate
    logger.info(f"Step 6.1: Using DROP DATABASE / CREATE DATABASE for clean slate")

    # Get root credentials for database operations
    db_root_password = os.environ.get("MYSQL_ROOT_PASSWORD")

    # Drop and recreate the database - this is the most reliable way to clear everything
    logger.info(f"Step 6.1.1: Dropping database {db_name}")
    drop_db_cmd = [
        "mysql",
        f"-h{db_host}",
        "-uroot",
        f"-p{db_root_password}",
        "--skip-ssl",
        "-e",
        f"DROP DATABASE IF EXISTS `{db_name}`;"
    ]

    try:
        result = subprocess.run(drop_db_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"Failed to drop database: {result.stderr}")
            raise Exception(f"Failed to drop database: {result.stderr}")
        logger.info(f"Database {db_name} dropped successfully")
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while dropping database")
        raise Exception("Timeout while dropping database")

    # Recreate the database
    logger.info(f"Step 6.1.2: Creating fresh database {db_name}")
    create_database_with_retry(db_host, db_root_password, db_name)

    # Grant permissions to the application user
    logger.info(f"Step 6.1.3: Granting permissions to user {db_user}")
    grant_cmd = [
        "mysql",
        f"-h{db_host}",
        "-uroot",
        f"-p{db_root_password}",
        "--skip-ssl",
        "-e",
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'%'; FLUSH PRIVILEGES;"
    ]

    try:
        result = subprocess.run(grant_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning(f"Failed to grant permissions: {result.stderr}")
            # Don't fail here, permissions might already exist
        else:
            logger.info(f"Permissions granted successfully")
    except Exception as e:
        logger.warning(f"Error granting permissions: {e}")

    logger.info(f"Step 6.2: Database completely reset and ready for restore")

    # Give a moment for database to be ready
    logger.info(f"Step 6.3: Waiting 2 seconds for database to be ready")
    time.sleep(2)


def reset_to_empty_instance():
    """Rebuild the schema after a failed setup restore, so setup can be tried again."""
    try:
        clear_database()
        subprocess.run(["alembic", "upgrade", "head"], cwd="/app", check=True, timeout=300)
    except Exception as e:
        logger.error(f"Could not reset the database after a failed setup restore: {e}")


# ---------------------------------------------------------------------------
# Helper: backup import with progress
# ---------------------------------------------------------------------------

def import_sql_file(mysql_cmd, sql_path, progress):
    """Feed a backup file to mysql a line at a time, reporting what was sent."""
    with open(sql_path, "rb") as f:
        table_count = sum(1 for line in f if TABLE_COMMENT_PATTERN.match(line))

    bytes_total = os.path.getsize(sql_path)
    bytes_done = 0
    table_number = 0
    table = None

    # stderr goes to a file so a noisy mysql can't fill a pipe and deadlock
    with tempfile.TemporaryFile() as stderr_file, open(sql_path, "rb") as f:
        with subprocess.Popen(mysql_cmd, stdin=subprocess.PIPE, stderr=stderr_file) as process:
            try:
                with process.stdin:
                    for line in f:
                        match = TABLE_COMMENT_PATTERN.match(line)
                        if match:
                            table_number += 1
                            table = match.group(1).decode("ascii")
                        process.stdin.write(line)
                        bytes_done += len(line)
                        progress.importing(table_number, table_count, table, bytes_done, bytes_total)
            except BrokenPipeError:
                # mysql stopped early. Its exit code and stderr say why.
                logger.warning("mysql closed its input before the whole backup was sent")

        if process.returncode != 0:
            stderr_file.seek(0)
            stderr = stderr_file.read().decode("utf-8", errors="replace")
            logger.error(f"MySQL restore failed with return code {process.returncode}: {stderr}")
            raise Exception(f"MySQL restore failed: {stderr}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@backup_bp.route("/api/database/backup", methods=["GET"])
@require_permission('admin.database')
def backup_database():
    """Create a database backup with version information.
    ---
    tags:
      - Database
    responses:
      200:
        description: Database backup file
        content:
          application/sql:
            schema:
              type: string
              format: binary
      500:
        description: Failed to create backup
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    try:
        # Get current Alembic version
        db = SessionLocal()
        result = db.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        db_version = row[0] if row else "unknown"
        db.close()

        # Get database credentials from environment
        db_user = os.environ.get("MYSQL_USER")
        db_password = os.environ.get("MYSQL_PASSWORD")
        db_name = os.environ.get("MYSQL_DATABASE")
        db_host = "db"

        # Create temporary file for backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"aft_backup_{timestamp}.sql"
        temp_file = tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".sql")
        temp_path = temp_file.name
        temp_file.close()

        # Write version comment to file
        with open(temp_path, "w") as f:
            f.write(f"-- AFT Database Backup\n")
            f.write(f"-- App Version: {_APP_VERSION}\n")
            f.write(f"-- Alembic Version: {db_version}\n")
            f.write(f"-- Backup Date: {datetime.now().isoformat()}\n")
            f.write(f"--\n\n")

        # Run mysqldump and append to file
        mysqldump_cmd = [
            "mysqldump",
            "-h",
            db_host,
            "-u",
            db_user,
            f"-p{db_password}",
            "--single-transaction",
            "--routines",
            "--triggers",
            "--skip-ssl",
            db_name,
        ]

        with open(temp_path, "a") as f:
            result = subprocess.run(
                mysqldump_cmd, stdout=f, stderr=subprocess.PIPE, text=True
            )

        if result.returncode != 0:
            os.unlink(temp_path)
            raise Exception(f"mysqldump failed: {result.stderr}")

        logger.info(f"Database backup created successfully: {backup_filename}")

        # Send file and delete after sending
        return send_file(
            temp_path,
            mimetype="application/sql",
            as_attachment=True,
            download_name=backup_filename,
        )

    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}")
        create_notification_internal(
            subject="⚠️ Database Backup Failed",
            message=f"Failed to create database backup: {str(e)}\n\nCheck server logs for details."
        )
        return jsonify({"success": False, "message": "Failed to create database backup"}), 500


@backup_bp.route("/api/database/backup/manual", methods=["POST"])
@require_permission('admin.database')
def create_manual_backup():
    """Create a manual backup and save to backups folder.
    ---
    tags:
      - Database
    responses:
      200:
        description: Backup created successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            filename:
              type: string
      500:
        description: Failed to create backup
    """
    try:
        # Get current Alembic version
        db = SessionLocal()
        result = db.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        db_version = row[0] if row else "unknown"
        db.close()

        # Get database credentials from environment
        db_user = os.environ.get("MYSQL_USER")
        db_password = os.environ.get("MYSQL_PASSWORD")
        db_name = os.environ.get("MYSQL_DATABASE")
        db_host = "db"

        # Create backup in the backups folder
        backup_dir = Path("/app/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"aft_backup_{timestamp}.sql"
        backup_path = backup_dir / backup_filename

        # Write version comment to file
        with open(backup_path, "w") as f:
            f.write(f"-- AFT Database Backup\n")
            f.write(f"-- App Version: {_APP_VERSION}\n")
            f.write(f"-- Alembic Version: {db_version}\n")
            f.write(f"-- Backup Date: {datetime.now().isoformat()}\n")
            f.write(f"--\n\n")

        # Run mysqldump and append to file
        mysqldump_cmd = [
            "mysqldump",
            "-h",
            db_host,
            "-u",
            db_user,
            f"-p{db_password}",
            "--single-transaction",
            "--routines",
            "--triggers",
            "--skip-ssl",
            db_name,
        ]

        with open(backup_path, "a") as f:
            result = subprocess.run(
                mysqldump_cmd, stdout=f, stderr=subprocess.PIPE, text=True
            )

        if result.returncode != 0:
            backup_path.unlink()
            raise Exception(f"mysqldump failed: {result.stderr}")

        logger.info(f"Manual database backup created successfully: {backup_filename}")

        return jsonify({
            "success": True,
            "message": f"Backup created successfully: {backup_filename}",
            "filename": backup_filename
        })

    except Exception as e:
        logger.error(f"Error creating manual backup: {str(e)}")
        create_notification_internal(
            subject="⚠️ Manual Backup Failed",
            message=f"Failed to create manual backup: {str(e)}\n\nCheck database connection and mysqldump availability in server logs."
        )
        return jsonify({"success": False, "message": "Failed to create manual backup"}), 500


@backup_bp.route("/api/database/restore", methods=["POST"])
@require_permission('admin.database')
def restore_database():
    """Restore database from backup file with version checking.
    ---
    tags:
      - Database
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: SQL backup file to restore
      - in: header
        name: X-Restore-Progress-Id
        type: string
        required: false
        description: Random 32 character hex id for reading progress from /api/database/restore/progress/{progress_id}
    responses:
      200:
        description: Database restored successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
      400:
        description: Invalid file or version mismatch
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
      500:
        description: Failed to restore database
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    progress = RestoreProgress(request.headers.get(RESTORE_PROGRESS_HEADER))
    try:
        return restore_uploaded_file(progress)
    except Exception as e:
        logger.error(f"=== Manual restore FAILED ===")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "message": str(e)}), 500


@backup_bp.route("/api/auth/setup/restore", methods=["POST"])
def setup_restore():
    """Restore a backup instead of creating the first administrator.

    Needs no session, because no accounts exist yet. It only works until setup
    is complete, the same as creating the first administrator.
    ---
    tags:
      - Authentication
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: SQL backup file to restore
      - in: header
        name: X-Restore-Progress-Id
        type: string
        required: false
        description: Random 32 character hex id for reading progress from /api/database/restore/progress/{progress_id}
    responses:
      200:
        description: Database restored. Sign in with an account from the backup.
      400:
        description: Invalid backup file
      403:
        description: Setup already complete
      409:
        description: A restore is already running
      500:
        description: Restore failed and the instance was returned to first-time setup
    """
    if not claim_setup_restore():
        return jsonify({"success": False, "message": "A restore is already running"}), 409

    try:
        db = SessionLocal()
        try:
            user_count = db.query(User).filter(
                User.is_active == True,
                User.password_hash.isnot(None)
            ).count()
        finally:
            db.close()

        if user_count > 0:
            return jsonify({
                "success": False,
                "message": "Setup is already complete. Please use the login page.",
            }), 403

        progress = RestoreProgress(request.headers.get(RESTORE_PROGRESS_HEADER))
        try:
            return restore_uploaded_file(progress)
        except Exception as e:
            logger.error(f"Restore during setup failed: {e}\n{traceback.format_exc()}")
            reset_to_empty_instance()
            return jsonify({
                "success": False,
                "message": "The backup could not be restored. Check the server logs for details.",
            }), 500
    except Exception as e:
        logger.error(f"Restore during setup could not run: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "message": "The backup could not be restored"}), 500
    finally:
        release_setup_restore()


def restore_uploaded_file(progress):
    """Replace the database with the backup uploaded in the current request."""
    logger.info(f"=== Starting manual restore from uploaded file ===")
    temp_path = None
    try:
        # Check if file was uploaded
        logger.info(f"Step 1: Validating file upload")
        if "file" not in request.files:
            logger.error("No file uploaded in request")
            return jsonify({"success": False, "message": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            logger.error("Empty filename provided")
            return jsonify({"success": False, "message": "No file selected"}), 400

        logger.info(f"Uploaded file: {file.filename}")
        logger.info(f"Step 2: Saving uploaded file to temporary location")
        # Save uploaded file to temporary location
        temp_file = tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".sql")
        temp_path = temp_file.name
        temp_file.close()
        file.save(temp_path)
        logger.info(f"File saved to: {temp_path}")

        logger.info(f"Step 3: Validating file size and security")
        progress.step("Checking the backup file")
        # File size validation: Check for reasonable size
        is_valid_size, size_error = validate_backup_file_size(temp_path, max_size_mb=MAX_BACKUP_FILE_SIZE_MB)
        if not is_valid_size:
            os.unlink(temp_path)
            logger.warning(f"File size validation failed: {size_error}")
            return jsonify({
                "success": False,
                "message": f"File size validation failed: {size_error}"
            }), 400

        # Security validation: Check for dangerous SQL patterns
        is_secure, security_error = validate_backup_file_security(temp_path)
        if not is_secure:
            os.unlink(temp_path)
            logger.warning(f"Security validation failed: {security_error}")
            return jsonify({
                "success": False,
                "message": f"Security validation failed: {security_error}"
            }), 400

        # Schema validation: Ensure only expected tables
        is_valid_schema, schema_error = validate_schema_integrity(temp_path)
        if not is_valid_schema:
            os.unlink(temp_path)
            logger.warning(f"Schema validation failed: {schema_error}")
            return jsonify({
                "success": False,
                "message": f"Schema validation failed: {schema_error}"
            }), 400

        logger.info(f"Step 4: Reading backup file to extract version information")
        # Read first few lines to get version info
        backup_version = None
        with open(temp_path, "r") as f:
            for line in f:
                if line.startswith("-- Alembic Version:"):
                    backup_version = line.split(":", 1)[1].strip()
                    break
                # Stop reading after comments section
                if not line.startswith("--") and line.strip():
                    break

        if not backup_version:
            os.unlink(temp_path)
            logger.error("No Alembic version found in backup file")
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Invalid backup file: No Alembic version found",
                    }
                ),
                400,
            )

        logger.info(f"Backup version: {backup_version}")
        logger.info(f"Step 5: Checking current database version")
        # Get current Alembic version (what we would create on restore)
        db = SessionLocal()
        result = db.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        current_version = row[0] if row else "unknown"
        db.close()
        logger.info(f"Current version: {current_version}")

        # Check version compatibility
        # Note: Alembic versions are revision IDs, not semantic versions
        # We can only reliably check equality; different versions require migration
        if backup_version != current_version:
            logger.warning(
                f"Backup version ({backup_version}) differs from current version ({current_version}). "
                "Will attempt to restore and upgrade."
            )

        logger.info(f"Step 6: Dropping all existing tables")
        progress.step("Clearing the existing database")
        clear_database()

        db_user = os.environ.get("MYSQL_USER")
        db_password = os.environ.get("MYSQL_PASSWORD")
        db_name = os.environ.get("MYSQL_DATABASE")
        db_host = "db"

        logger.info(f"Step 7: Restoring data from backup file using mysql command")
        logger.info(f"Restoring database from backup (version {backup_version})")

        # Restore from SQL file
        mysql_cmd = [
            "mysql",
            "-h",
            db_host,
            "-u",
            db_user,
            f"-p{db_password}",
            "--skip-ssl",
            db_name,
        ]

        import_sql_file(mysql_cmd, temp_path, progress)
        os.unlink(temp_path)

        logger.info(f"MySQL restore completed successfully")

        # Verify database connection is working after restore
        logger.info(f"Step 7.1: Verifying database connection after restore")
        max_retries = 10
        retry_delay = 2
        connected = False

        for attempt in range(1, max_retries + 1):
            try:
                test_db = SessionLocal()
                test_db.execute(text("SELECT 1"))
                test_db.close()
                logger.info(f"Database connection verified on attempt {attempt}")
                connected = True
                break
            except Exception as e:
                logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    raise Exception(f"Failed to verify database connection after {max_retries} attempts")

        logger.info(f"Step 7.5: Cleaning up scheduler lock files after restore")
        # Clean up stale scheduler lock files after successful restore
        # This forces the scheduler threads to create fresh lock files with current timestamps
        # Otherwise the system info page will show stale heartbeat ages from before the restore
        logger.info("Cleaning up scheduler lock files after restore")
        temp_dir = Path(tempfile.gettempdir())
        lock_files_to_clean = [
            temp_dir / "aft_backup_scheduler.lock",
            temp_dir / "aft_card_scheduler.lock",
            temp_dir / "aft_housekeeping_scheduler.lock",
        ]

        for lock_file in lock_files_to_clean:
            try:
                if lock_file.exists():
                    lock_file.unlink()
                    logger.info(f"Cleaned up scheduler lock file after restore: {lock_file}")
            except Exception as e:
                logger.warning(f"Failed to clean lock file {lock_file}: {e}")

        # If backup version differs from current, run migrations to upgrade
        if backup_version != current_version:
            logger.info(f"Step 8: Running Alembic migrations from {backup_version} to {current_version}")
            progress.step("Upgrading the restored database")
            logger.info(
                f"Migrating database from {backup_version} to {current_version}"
            )
            # Use stdout=None, stderr=None to avoid subprocess deadlock from filled pipes
            # Output will flow to parent process logs
            upgrade_result = subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd="/app",
                stdout=None,
                stderr=None,
                text=True,
            )

            if upgrade_result.returncode != 0:
                logger.error(f"Alembic upgrade failed with return code {upgrade_result.returncode}")
                raise Exception(f"Alembic upgrade failed - check server logs for details")

            logger.info(f"Alembic migrations completed successfully")
            logger.info(f"=== Manual restore completed successfully (with migration) ===")
            return jsonify(
                {
                    "success": True,
                    "message": f"Database restored and upgraded from version {backup_version} to {current_version}",
                }
            )
        else:
            logger.info(f"Step 8: No migration needed, versions match")
            logger.info(f"=== Manual restore completed successfully (no migration) ===")
            logger.info("Database restored successfully")
            return jsonify(
                {"success": True, "message": "Database restored successfully"}
            )

    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@backup_bp.route("/api/database/restore/progress/<progress_id>", methods=["GET"])
def restore_progress(progress_id):
    """Get the progress of a running restore.

    Needs no session, because the database is unavailable for part of a
    restore. The id is a random value the page sent with the restore request.
    ---
    tags:
      - Database
    parameters:
      - name: progress_id
        in: path
        type: string
        required: true
        description: The 32 character hex id sent in the X-Restore-Progress-Id header of the restore request
    responses:
      200:
        description: The latest progress, or null if the restore has not reported any yet
        schema:
          type: object
          properties:
            success:
              type: boolean
            progress:
              type: object
              properties:
                message:
                  type: string
                bytes_done:
                  type: integer
                  description: Bytes of the backup sent to MySQL, only while importing
                bytes_total:
                  type: integer
                  description: Size of the backup, only while importing
      400:
        description: Invalid progress id
    """
    if not is_valid_progress_id(progress_id):
        return jsonify({"success": False, "message": "Invalid progress id"}), 400

    return jsonify({"success": True, "progress": read_progress(progress_id)})


@backup_bp.route("/api/database/backups/list", methods=["GET"])
@require_permission('admin.database')
def list_backups():
    """List all available backup files (both automatic and manual).
    ---
    tags:
      - Database
    responses:
      200:
        description: List of available backups
        schema:
          type: object
          properties:
            success:
              type: boolean
            backups:
              type: array
              items:
                type: object
                properties:
                  filename:
                    type: string
                  created:
                    type: string
                  size:
                    type: integer
                  is_manual:
                    type: boolean
                    description: True if manually created, False if automatic
      500:
        description: Failed to list backups
    """
    try:
        backup_dir = Path("/app/backups")

        if not backup_dir.exists():
            return jsonify({"success": True, "backups": []})

        backups = []
        for backup_file in backup_dir.glob("*.sql"):
            stat = backup_file.stat()
            is_manual = not backup_file.name.startswith("auto_backup_")
            backups.append({
                "filename": backup_file.name,
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size": stat.st_size,
                "is_manual": is_manual,
                "mtime": stat.st_mtime  # For sorting
            })

        # Sort by modification time, newest first
        backups.sort(key=lambda x: x["mtime"], reverse=True)

        # Remove mtime from response
        for backup in backups:
            del backup["mtime"]

        return jsonify({"success": True, "backups": backups})

    except Exception as e:
        logger.error(f"Error listing backups: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@backup_bp.route("/api/database/backups/restore/<filename>", methods=["POST"])
@require_permission('admin.database')
def restore_backup_from_file(filename):
    """Restore from a specific backup file (automatic or manual).
    ---
    tags:
      - Database
    parameters:
      - name: filename
        in: path
        type: string
        required: true
        description: The backup filename to restore from
      - in: header
        name: X-Restore-Progress-Id
        type: string
        required: false
        description: Random 32 character hex id for reading progress from /api/database/restore/progress/{progress_id}
    responses:
      200:
        description: Database restored successfully
      400:
        description: Invalid backup file
      404:
        description: Backup file not found
      500:
        description: Failed to restore backup
    """
    logger.info(f"=== Starting restore from backup: {filename} ===")
    progress = RestoreProgress(request.headers.get(RESTORE_PROGRESS_HEADER))
    try:
        # Validate filename to prevent path traversal
        # Allow both auto_backup and manual backup filenames (aft_backup)
        logger.info(f"Step 1: Validating filename format")
        if not re.match(r'^(auto_backup_|aft_backup_)\d{8}_\d{6}\.sql$', filename):
            logger.error(f"Invalid filename format: {filename}")
            return jsonify({"success": False, "message": "Invalid backup filename"}), 400

        logger.info(f"Step 2: Checking backup file exists and is not a symlink")
        backup_dir = Path("/app/backups")
        backup_path = backup_dir / filename

        # Check for symlinks before resolving (security: prevent symlink-based path traversal)
        if backup_path.is_symlink():
            logger.warning(f"Attempted to restore from symlink: {filename}")
            return jsonify({"success": False, "message": "Symlinks are not allowed"}), 400

        # Resolve path and ensure it's strictly within backup_dir (no traversal)
        resolved_backup_path = backup_path.resolve()
        resolved_backup_dir = backup_dir.resolve()
        try:
            resolved_backup_path.relative_to(resolved_backup_dir)
        except ValueError:
            logger.warning(f"Path traversal attempt detected: {filename}")
            return jsonify({"success": False, "message": "Invalid backup file path"}), 400

        if not resolved_backup_path.exists():
            logger.error(f"Backup file not found: {resolved_backup_path}")
            return jsonify({"success": False, "message": "Backup file not found"}), 404

        logger.info(f"Step 3: Validating file size and security")
        progress.step("Checking the backup file")
        # File size validation
        is_valid_size, size_error = validate_backup_file_size(resolved_backup_path, max_size_mb=MAX_BACKUP_FILE_SIZE_MB)
        if not is_valid_size:
            logger.warning(f"File size validation failed for {filename}: {size_error}")
            return jsonify({
                "success": False,
                "message": f"File size validation failed: {size_error}"
            }), 400

        # Security validation: Check for dangerous SQL patterns
        is_secure, security_error = validate_backup_file_security(resolved_backup_path)
        if not is_secure:
            logger.warning(f"Security validation failed for {filename}: {security_error}")
            return jsonify({
                "success": False,
                "message": f"Security validation failed: {security_error}"
            }), 400

        # Schema validation: Ensure only expected tables
        is_valid_schema, schema_error = validate_schema_integrity(resolved_backup_path)
        if not is_valid_schema:
            logger.warning(f"Schema validation failed for {filename}: {schema_error}")
            return jsonify({
                "success": False,
                "message": f"Schema validation failed: {schema_error}"
            }), 400

        logger.info(f"Step 4: Reading backup file to extract version information")
        # Read and validate the backup file
        with open(resolved_backup_path, 'r') as f:
            content = f.read(10000)  # Read first 10KB to find version

        # Extract Alembic version from backup
        version_match = re.search(r"-- Alembic Version: (\S+)", content)
        if not version_match:
            return jsonify({
                "success": False,
                "message": "Invalid backup file: No Alembic version found"
            }), 400

        backup_version = version_match.group(1)
        logger.info(f"Backup version: {backup_version}")

        # Get current Alembic version
        logger.info(f"Step 5: Checking current database version")
        db = SessionLocal()
        result = db.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        current_version = row[0] if row else "unknown"
        db.close()
        logger.info(f"Current version: {current_version}")

        # Check version compatibility
        # Note: Alembic versions are revision IDs, not semantic versions
        # We can only reliably check equality; different versions require migration
        if backup_version != current_version:
            logger.warning(
                f"Backup version ({backup_version}) differs from current version ({current_version}). "
                "Will attempt to restore and upgrade."
            )

        # Get database credentials
        db_user = os.environ.get("MYSQL_USER")
        db_password = os.environ.get("MYSQL_PASSWORD")
        db_name = os.environ.get("MYSQL_DATABASE")
        db_host = "db"

        logger.info(f"Step 6: Dropping all existing tables")
        progress.step("Clearing the existing database")

        # Close any existing database sessions in this request context to avoid connection issues
        logger.info(f"Step 6.0: Closing request database sessions before killing connections")
        request_db = g.pop('db', None)
        if request_db:
            try:
                request_db.close()
                logger.info(f"Closed request database session")
            except Exception as e:
                logger.warning(f"Error closing request database session: {e}")

        # Dispose of SQLAlchemy engine connection pool so it creates fresh connections
        try:
            engine.dispose()
            logger.info(f"Disposed SQLAlchemy engine connection pool")
        except Exception as e:
            logger.warning(f"Error disposing engine pool: {e}")

        # Kill all other database connections first to release locks
        logger.info(f"Step 6.0.1: Killing all other database connections to release locks")
        get_pids_cmd = [
            "mysql",
            f"-h{db_host}",
            f"-u{db_user}",
            f"-p{db_password}",
            "--skip-ssl",
            "-N",
            "-e",
            f"SELECT id FROM INFORMATION_SCHEMA.PROCESSLIST WHERE db = '{db_name}' AND id != CONNECTION_ID();"
        ]

        try:
            result = subprocess.run(get_pids_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                pids = [pid.strip() for pid in result.stdout.strip().split('\n') if pid.strip()]
                logger.info(f"Found {len(pids)} active connections to kill: {pids}")

                for pid in pids:
                    logger.info(f"Killing connection: {pid}")
                    kill_cmd = [
                        "mysql",
                        f"-h{db_host}",
                        f"-u{db_user}",
                        f"-p{db_password}",
                        "--skip-ssl",
                        "-e",
                        f"KILL {pid};"
                    ]
                    try:
                        subprocess.run(kill_cmd, capture_output=True, text=True, timeout=5)
                        logger.info(f"Killed connection: {pid}")
                    except Exception as e:
                        logger.warning(f"Could not kill connection {pid}: {e}")

                logger.info(f"Step 6.0.2: Waiting 2 seconds for connections to terminate")
                time.sleep(2)
            else:
                logger.info(f"No active connections to kill")
        except Exception as e:
            logger.warning(f"Error killing connections: {e}")

        # Use DROP DATABASE / CREATE DATABASE for a completely clean slate
        logger.info(f"Step 6.1: Using DROP DATABASE / CREATE DATABASE for clean slate")

        # Get root credentials for database operations
        db_root_password = os.environ.get("MYSQL_ROOT_PASSWORD")

        # Drop and recreate the database - this is the most reliable way to clear everything
        logger.info(f"Step 6.1.1: Dropping database {db_name}")
        drop_db_cmd = [
            "mysql",
            f"-h{db_host}",
            "-uroot",
            f"-p{db_root_password}",
            "--skip-ssl",
            "-e",
            f"DROP DATABASE IF EXISTS `{db_name}`;"
        ]

        try:
            result = subprocess.run(drop_db_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"Failed to drop database: {result.stderr}")
                raise Exception(f"Failed to drop database: {result.stderr}")
            logger.info(f"Database {db_name} dropped successfully")
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout while dropping database")
            raise Exception("Timeout while dropping database")

        # Recreate the database
        logger.info(f"Step 6.1.2: Creating fresh database {db_name}")
        create_database_with_retry(db_host, db_root_password, db_name)

        # Grant permissions to the application user
        logger.info(f"Step 6.1.3: Granting permissions to user {db_user}")
        grant_cmd = [
            "mysql",
            f"-h{db_host}",
            "-uroot",
            f"-p{db_root_password}",
            "--skip-ssl",
            "-e",
            f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'%'; FLUSH PRIVILEGES;"
        ]

        try:
            result = subprocess.run(grant_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.warning(f"Failed to grant permissions: {result.stderr}")
                # Don't fail here, permissions might already exist
            else:
                logger.info(f"Permissions granted successfully")
        except Exception as e:
            logger.warning(f"Error granting permissions: {e}")

        logger.info(f"Step 6.2: Database completely reset and ready for restore")

        # Give a moment for database to be ready
        logger.info(f"Step 6.3: Waiting 2 seconds for database to be ready")
        time.sleep(2)

        logger.info(f"Step 7: Restoring data from backup file using mysql command")
        # Restore from backup file
        mysql_cmd = [
            "mysql",
            f"-h{db_host}",
            f"-u{db_user}",
            f"-p{db_password}",
            "--skip-ssl",
            db_name,
        ]

        import_sql_file(mysql_cmd, resolved_backup_path, progress)

        logger.info(f"MySQL restore completed successfully")

        # Clean up stale scheduler lock files after successful restore
        # This forces the scheduler threads to create fresh lock files with current timestamps
        logger.info(f"Step 7.5: Cleaning up scheduler lock files after restore")
        temp_dir = Path(tempfile.gettempdir())
        lock_files_to_clean = [
            temp_dir / "aft_backup_scheduler.lock",
            temp_dir / "aft_card_scheduler.lock",
            temp_dir / "aft_housekeeping_scheduler.lock",
        ]

        for lock_file in lock_files_to_clean:
            try:
                if lock_file.exists():
                    lock_file.unlink()
                    logger.info(f"Cleaned up scheduler lock file: {lock_file}")
            except Exception as e:
                logger.warning(f"Failed to clean lock file {lock_file}: {e}")

        # Run migrations if needed
        if backup_version != current_version:
            logger.info(f"Step 8: Running Alembic migrations from {backup_version} to {current_version}")
            progress.step("Upgrading the restored database")
            # Use stdout=None, stderr=None to avoid subprocess deadlock from filled pipes
            # Output will flow to parent process logs
            upgrade_result = subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd="/app",
                stdout=None,
                stderr=None,
                text=True,
            )

            if upgrade_result.returncode != 0:
                logger.error(f"Alembic upgrade failed with return code {upgrade_result.returncode}")
                raise Exception(f"Alembic upgrade failed - check server logs for details")

            logger.info(f"Alembic migrations completed successfully")

            logger.info(f"=== Restore completed successfully: {filename} (with migration) ===")
            return jsonify({
                "success": True,
                "message": f"Database restored from {filename} and upgraded to version {current_version}"
            })
        else:
            logger.info(f"Step 8: No migration needed, versions match")
            logger.info(f"=== Restore completed successfully: {filename} (no migration) ===")
            return jsonify({
                "success": True,
                "message": f"Database restored successfully from {filename}"
            })

    except Exception as e:
        logger.error(f"=== Restore FAILED for {filename} ===")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "message": str(e)}), 500


@backup_bp.route("/api/database/backups/delete/<filename>", methods=["DELETE"])
@require_permission('admin.database')
def delete_backup(filename):
    """Delete a specific backup file.
    ---
    tags:
      - Database
    parameters:
      - name: filename
        in: path
        type: string
        required: true
        description: The backup filename to delete
    responses:
      200:
        description: Backup deleted successfully
      400:
        description: Invalid backup file
      404:
        description: Backup file not found
      500:
        description: Failed to delete backup
    """
    try:
        # Validate filename to prevent path traversal
        # Allow both auto_backup and manual backup filenames (aft_backup)
        if not re.match(r'^(auto_backup_|aft_backup_)\d{8}_\d{6}\.sql$', filename):
            return jsonify({"success": False, "message": "Invalid backup filename"}), 400

        backup_dir = Path("/app/backups")
        backup_path = backup_dir / filename

        if not backup_path.exists():
            return jsonify({"success": False, "message": "Backup file not found"}), 404

        # Delete the backup file
        backup_path.unlink()

        logger.info(f"Backup deleted successfully: {filename}")
        return jsonify({
            "success": True,
            "message": f"Backup {filename} deleted successfully"
        })

    except Exception as e:
        logger.error(f"Error deleting backup: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@backup_bp.route("/api/database/backups/delete-multiple", methods=["POST"])
@require_permission('admin.database')
def delete_multiple_backups():
    """Delete multiple backup files.
    ---
    tags:
      - Database
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - filenames
          properties:
            filenames:
              type: array
              items:
                type: string
              description: Array of backup filenames to delete
    responses:
      200:
        description: Backups deleted successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            deleted:
              type: integer
              description: Number of backups successfully deleted
            failed:
              type: integer
              description: Number of backups that failed to delete
            errors:
              type: array
              items:
                type: string
              description: List of error messages for failed deletions
      400:
        description: Invalid request
      500:
        description: Failed to delete backups
    """
    try:
        data = request.get_json()

        if not data or 'filenames' not in data:
            return jsonify({"success": False, "message": "Missing filenames array"}), 400

        filenames = data['filenames']

        if not isinstance(filenames, list):
            return jsonify({"success": False, "message": "filenames must be an array"}), 400

        if len(filenames) == 0:
            return jsonify({"success": False, "message": "filenames array is empty"}), 400

        if len(filenames) > 100:
            return jsonify({"success": False, "message": "Cannot delete more than 100 backups at once"}), 400

        backup_dir = Path("/app/backups")
        deleted_count = 0
        failed_count = 0
        errors = []

        for filename in filenames:
            try:
                # Validate filename to prevent path traversal
                if not re.match(r'^(auto_backup_|aft_backup_)\d{8}_\d{6}\.sql$', filename):
                    errors.append(f"{filename}: Invalid backup filename")
                    failed_count += 1
                    continue

                backup_path = backup_dir / filename

                if not backup_path.exists():
                    errors.append(f"{filename}: File not found")
                    failed_count += 1
                    continue

                # Delete the backup file
                backup_path.unlink()
                deleted_count += 1

            except Exception as e:
                errors.append(f"{filename}: {str(e)}")
                failed_count += 1

        logger.info(f"Bulk delete completed: {deleted_count} deleted, {failed_count} failed")

        return jsonify({
            "success": True,
            "deleted": deleted_count,
            "failed": failed_count,
            "errors": errors,
            "message": f"Deleted {deleted_count} backup(s)" + (f", {failed_count} failed" if failed_count > 0 else "")
        })

    except Exception as e:
        logger.error(f"Error in bulk delete: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@backup_bp.route("/api/database", methods=["DELETE"])
@require_permission('admin.database')
def delete_database():
    """Delete all data from the database.
    ---
    tags:
      - Database
    responses:
      200:
        description: Database deleted successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Database deleted successfully"
      500:
        description: Failed to delete database
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    try:
        # Get database credentials
        db_user = os.environ.get("MYSQL_USER")
        db_password = os.environ.get("MYSQL_PASSWORD")
        db_name = os.environ.get("MYSQL_DATABASE")
        db_root_password = os.environ.get("MYSQL_ROOT_PASSWORD")
        db_host = "db"

        if not db_user or not db_password or not db_name:
            raise Exception("Missing required database environment variables")

        lock_path = "/tmp/aft_db_reset.lock"
        lock_fd = None

        def acquire_reset_lock(timeout_seconds=60):
            start = time.time()
            while True:
                try:
                    return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    # Recover from stale lock files left by terminated processes.
                    try:
                        if time.time() - os.path.getmtime(lock_path) > 600:
                            os.remove(lock_path)
                            continue
                    except FileNotFoundError:
                        continue

                    if time.time() - start > timeout_seconds:
                        return None
                    time.sleep(0.2)

        def wait_for_schema_ready(timeout_seconds=120):
            """Wait for critical tables to appear when another reset is running."""
            start = time.time()
            while time.time() - start <= timeout_seconds:
                check_cmd = [
                    "mysql",
                    f"-h{db_host}",
                    f"-u{db_user}",
                    f"-p{db_password}",
                    "--skip-ssl",
                    db_name,
                    "-N",
                    "-e",
                    "SHOW TABLES LIKE 'users'; SHOW TABLES LIKE 'settings';"
                ]

                check_result = subprocess.run(
                    check_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if check_result.returncode == 0:
                    table_lines = {line.strip() for line in check_result.stdout.splitlines() if line.strip()}
                    if "users" in table_lines and "settings" in table_lines:
                        return

                time.sleep(1)

            raise Exception("Timed out waiting for in-progress database reset to complete")

        def release_reset_lock(fd):
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                try:
                    os.remove(lock_path)
                except FileNotFoundError:
                    pass

        def ensure_database_exists_with_root():
            if not db_root_password:
                return

            create_if_missing_cmd = [
                "mysql",
                f"-h{db_host}",
                "-uroot",
                f"-p{db_root_password}",
                "--skip-ssl",
                "-e",
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            ]

            create_result = subprocess.run(
                create_if_missing_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if create_result.returncode != 0:
                raise Exception(f"Failed to ensure database exists: {create_result.stderr}")

            grant_cmd = [
                "mysql",
                f"-h{db_host}",
                "-uroot",
                f"-p{db_root_password}",
                "--skip-ssl",
                "-e",
                f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'%'; FLUSH PRIVILEGES;"
            ]

            grant_result = subprocess.run(
                grant_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if grant_result.returncode != 0:
                logger.warning(f"Failed to grant permissions during reset: {grant_result.stderr}")

        def drop_all_tables_with_app_user():
            """Drop all tables in the target schema using the app DB user."""
            get_tables_cmd = [
                "mysql",
                f"-h{db_host}",
                f"-u{db_user}",
                f"-p{db_password}",
                "--skip-ssl",
                db_name,
                "-N",
                "-e",
                "SHOW TABLES;"
            ]

            tables_result = subprocess.run(
                get_tables_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if tables_result.returncode != 0:
                raise Exception(f"Failed to list tables: {tables_result.stderr}")

            tables = [t.strip() for t in tables_result.stdout.strip().split('\n') if t.strip()]
            logger.info(f"Found {len(tables)} tables to delete")

            if tables:
                drop_statements = "SET FOREIGN_KEY_CHECKS = 0; "
                for table in tables:
                    drop_statements += f"DROP TABLE IF EXISTS `{table}`; "
                drop_statements += "SET FOREIGN_KEY_CHECKS = 1;"

                drop_cmd = [
                    "mysql",
                    f"-h{db_host}",
                    f"-u{db_user}",
                    f"-p{db_password}",
                    "--skip-ssl",
                    db_name,
                    "-e",
                    drop_statements
                ]

                drop_result = subprocess.run(
                    drop_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if drop_result.returncode != 0:
                    raise Exception(f"Failed to drop tables: {drop_result.stderr}")

        lock_fd = acquire_reset_lock()
        if lock_fd is None:
            logger.info("Database reset already in progress; waiting for completion")
            wait_for_schema_ready()
            return jsonify({"success": True, "message": "Database reset completed by another request"})

        os.write(lock_fd, str(os.getpid()).encode("utf-8"))

        # Reset connection pools before destructive DB operations.
        try:
            engine.dispose()
            logger.info("Disposed SQLAlchemy engine connection pool")
        except Exception as e:
            logger.warning(f"Error disposing engine pool: {e}")

        # Kill active database connections to prevent metadata lock timeouts.
        try:
            get_pids_cmd = [
                "mysql",
                f"-h{db_host}",
                f"-u{db_user}",
                f"-p{db_password}",
                "--skip-ssl",
                "-N",
                "-e",
                f"SELECT id FROM INFORMATION_SCHEMA.PROCESSLIST WHERE db = '{db_name}' AND id != CONNECTION_ID();"
            ]

            pids_result = subprocess.run(
                get_pids_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if pids_result.returncode == 0 and pids_result.stdout.strip():
                pids = [pid.strip() for pid in pids_result.stdout.strip().split('\n') if pid.strip()]
                logger.info(f"Found {len(pids)} active connections to kill: {pids}")

                for pid in pids:
                    kill_cmd = [
                        "mysql",
                        f"-h{db_host}",
                        f"-u{db_user}",
                        f"-p{db_password}",
                        "--skip-ssl",
                        "-e",
                        f"KILL {pid};"
                    ]
                    try:
                        subprocess.run(kill_cmd, capture_output=True, text=True, timeout=5)
                    except Exception as e:
                        logger.warning(f"Could not kill connection {pid}: {e}")

                time.sleep(1)
            else:
                logger.info("No active connections to kill")
        except Exception as e:
            logger.warning(f"Error killing connections before reset: {e}")

        # Keep schema in place and reset at table-level to avoid drop/create races.
        ensure_database_exists_with_root()
        drop_all_tables_with_app_user()

        # Run Alembic migrations to recreate database with proper version tracking
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            raise Exception(f"Alembic migration failed: {result.stderr}")

        logger.info("Database deleted and recreated successfully via Alembic migrations")
        return jsonify({"success": True, "message": "Database deleted successfully"})
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while deleting database")
        return jsonify({"success": False, "message": "Timeout while deleting database"}), 500
    except Exception as e:
        logger.error(f"Error deleting database: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if lock_fd is not None:
            release_reset_lock(lock_fd)

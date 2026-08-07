"""
Security tests for database backup/restore functionality.

Tests SQL injection patterns, schema validation, file size limits,
and malicious content detection.
"""
import pytest
import tempfile
import os

@pytest.fixture(autouse=True)
def _backup_security_env(monkeypatch):
    """Scope auth-related env vars to each test to avoid cross-test leakage."""
    # These tests validate backup SQL/file security logic and do not depend on
    # server-side session backend mode.
    monkeypatch.setenv('ENABLE_SERVER_SIDE_SESSIONS', 'false')
    monkeypatch.setenv('AFT_SKIP_SCHEDULER_INIT', 'true')

    # Provide a deterministic test secret only when one is not already set.
    current_secret = os.environ.get('SECRET_KEY', 'unit-test-secret-key')
    monkeypatch.setenv('SECRET_KEY', current_secret)


# Test fixtures for SQL content
VALID_BACKUP_HEADER = """-- AFT Database Backup
-- Alembic Version: 008
-- Date: 2025-11-30 12:00:00

"""

VALID_TABLE_STRUCTURE = """
DROP TABLE IF EXISTS `boards`;
CREATE TABLE `boards` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS `columns`;
CREATE TABLE `columns` (
  `id` int NOT NULL AUTO_INCREMENT,
  `board_id` int NOT NULL,
  `name` varchar(255) NOT NULL,
  `position` int NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS `cards`;
CREATE TABLE `cards` (
  `id` int NOT NULL AUTO_INCREMENT,
  `column_id` int NOT NULL,
  `title` varchar(255) NOT NULL,
  `description` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS `checklist_items`;
CREATE TABLE `checklist_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `card_id` int NOT NULL,
  `text` varchar(500) NOT NULL,
  `is_checked` tinyint(1) DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS `comments`;
CREATE TABLE `comments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `card_id` int NOT NULL,
  `text` text NOT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS `settings`;
CREATE TABLE `settings` (
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS `alembic_version`;
CREATE TABLE `alembic_version` (
  `version_num` varchar(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO `alembic_version` VALUES ('008');
"""


def create_test_backup_file(content, size_mb=None):
    """Create a temporary backup file with given content.
    
    Args:
        content: SQL content to write
        size_mb: If specified, pad file to this size in MB
        
    Returns:
        Path to temporary file
    """
    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.sql')
    temp_file.write(content)
    
    if size_mb:
        # Add padding comments to reach desired size
        current_size = len(content.encode('utf-8'))
        target_size = size_mb * 1024 * 1024
        remaining = target_size - current_size
        
        if remaining > 0:
            # Write padding in chunks to avoid memory issues
            chunk_size = 1024 * 1024  # 1MB chunks
            padding_line = "-- " + "x" * 1020 + "\n"  # ~1KB per line
            
            while remaining > 0:
                write_size = min(chunk_size, remaining)
                lines_to_write = int(write_size // len(padding_line.encode('utf-8')))
                for _ in range(lines_to_write):
                    temp_file.write(padding_line)
                remaining -= write_size
    
    temp_file.close()
    return temp_file.name


class TestSQLPatternValidation:
    """Test detection of dangerous SQL patterns."""
    
    def test_valid_backup_passes(self):
        """Valid backup file should pass all validations."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert is_valid, f"Valid backup failed validation: {error}"
        finally:
            os.unlink(filepath)
    
    def test_grant_statement_detected(self):
        """GRANT statements should be blocked."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nGRANT ALL PRIVILEGES ON *.* TO 'attacker'@'%';\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "GRANT statement should be blocked"
            assert error and "GRANT" in error
        finally:
            os.unlink(filepath)
    
    def test_create_user_detected(self):
        """CREATE USER statements should be blocked."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nCREATE USER 'attacker'@'localhost' IDENTIFIED BY 'password';\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "CREATE USER should be blocked"
            assert error and "CREATE USER" in error
        finally:
            os.unlink(filepath)
    
    def test_into_outfile_detected(self):
        """INTO OUTFILE statements should be blocked."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nSELECT * FROM boards INTO OUTFILE '/tmp/exploit.txt';\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "INTO OUTFILE should be blocked"
            assert error and "OUTFILE" in error
        finally:
            os.unlink(filepath)
    
    def test_load_data_detected(self):
        """LOAD DATA statements should be blocked."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nLOAD DATA INFILE '/etc/passwd' INTO TABLE boards;\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "LOAD DATA should be blocked"
            assert error and "LOAD DATA" in error
        finally:
            os.unlink(filepath)
    
    def test_stored_procedure_detected(self):
        """CREATE PROCEDURE statements should be blocked."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nCREATE PROCEDURE evil_proc() BEGIN SELECT 1; END;\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "CREATE PROCEDURE should be blocked"
            assert error and ("PROCEDURE" in error or "procedures" in error)
        finally:
            os.unlink(filepath)
    
    def test_use_statement_detected(self):
        """USE statements should be blocked."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nUSE mysql;\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "USE statement should be blocked"
            assert error and "USE" in error
        finally:
            os.unlink(filepath)
    
    def test_shell_command_detected(self):
        """MySQL shell commands should be blocked."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\n\\! rm -rf /\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "Shell command should be blocked"
            assert error and "shell" in error.lower()
        finally:
            os.unlink(filepath)
    
    def test_prepare_statement_detected(self):
        """PREPARE statements should be blocked."""
        from app import validate_backup_file_security

        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nPREPARE stmt FROM 'SELECT * FROM boards';\n"
        filepath = create_test_backup_file(content)

        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "PREPARE statement should be blocked"
            assert error and "Prepared" in error
        finally:
            os.unlink(filepath)

    def test_prepare_word_in_data_value_not_detected(self):
        """A card/row value that merely contains the word 'Prepare' (e.g. a
        card titled 'Prepare flower bed') must not be treated as a dangerous
        PREPARE statement."""
        from app import validate_backup_file_security

        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += (
            "\nINSERT INTO `cards` (`id`, `column_id`, `title`, `description`) VALUES "
            "(1,1,'Prepare flower bed',NULL);\n"
        )
        filepath = create_test_backup_file(content)

        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert is_valid, f"Data value containing 'Prepare' should not be blocked: {error}"
        finally:
            os.unlink(filepath)

    @pytest.mark.parametrize(
        "statement,expected_substring",
        [
            ("GRANT ALL PRIVILEGES ON *.* TO 'attacker'@'%';", "GRANT"),
            ("CREATE USER 'attacker'@'localhost' IDENTIFIED BY 'password';", "CREATE USER"),
            ("DROP USER 'attacker'@'localhost';", "DROP USER"),
            ("ALTER USER 'attacker'@'localhost' IDENTIFIED BY 'password';", "ALTER USER"),
            ("LOAD DATA INFILE '/etc/passwd' INTO TABLE boards;", "LOAD DATA"),
            ("CREATE PROCEDURE evil_proc() BEGIN SELECT 1; END;", "procedures"),
            ("EXECUTE stmt;", "Dynamic SQL"),
            ("PREPARE stmt FROM 'SELECT * FROM boards';", "Prepared"),
        ],
    )
    def test_dangerous_statement_after_semicolon_on_same_line_detected(
        self, statement, expected_substring
    ):
        """A dangerous statement smuggled after a leading throwaway statement
        on the same line (e.g. "SELECT 1; GRANT ...;") must still be
        blocked, not just dangerous statements that start the line."""
        from app import validate_backup_file_security

        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += f"\nSELECT 1; {statement}\n"
        filepath = create_test_backup_file(content)

        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, (
                f"Statement smuggled after ';' on the same line should be blocked: {statement}"
            )
            assert error and expected_substring in error
        finally:
            os.unlink(filepath)


class TestSchemaValidation:
    """Test schema integrity validation."""
    
    def test_valid_schema_passes(self):
        """Valid AFT schema should pass validation."""
        from app import validate_schema_integrity
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_schema_integrity(filepath)
            assert is_valid, f"Valid schema failed validation: {error}"
        finally:
            os.unlink(filepath)
    
    def test_unexpected_table_detected(self):
        """Unexpected tables should be detected."""
        from app import validate_schema_integrity
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nCREATE TABLE `malicious_table` (id INT);\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_schema_integrity(filepath)
            assert not is_valid, "Unexpected table should be detected"
            assert error and "malicious_table" in error
        finally:
            os.unlink(filepath)
    
    def test_missing_core_tables_detected(self):
        """Backup without core tables should be rejected."""
        from app import validate_schema_integrity
        
        content = VALID_BACKUP_HEADER
        content += "\nCREATE TABLE `settings` (key VARCHAR(255));\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_schema_integrity(filepath)
            assert not is_valid, "Missing core tables should be detected"
            assert error and "valid AFT database schema" in error
        finally:
            os.unlink(filepath)


class TestFileSizeValidation:
    """Test file size limits."""
    
    def test_small_file_passes(self):
        """Small valid backup should pass."""
        from app import validate_backup_file_size
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_size(filepath, max_size_mb=100)
            assert is_valid, f"Small file failed validation: {error}"
        finally:
            os.unlink(filepath)
    
    def test_file_at_limit_passes(self):
        """File near the size limit should pass."""
        from app import validate_backup_file_size
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        # Create ~4.5MB file to test without exceeding limit
        filepath = create_test_backup_file(content, size_mb=4.5)
        
        try:
            is_valid, error = validate_backup_file_size(filepath, max_size_mb=5)
            assert is_valid, f"File under limit should pass: {error}"
        finally:
            os.unlink(filepath)
    
    def test_oversized_file_rejected(self):
        """File over size limit should be rejected."""
        from app import validate_backup_file_size
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        # Create 2MB file and test with 1MB limit
        filepath = create_test_backup_file(content, size_mb=2)
        
        try:
            is_valid, error = validate_backup_file_size(filepath, max_size_mb=1)
            assert not is_valid, "Oversized file should be rejected"
            assert error and "exceeds" in error
        finally:
            os.unlink(filepath)
    
    def test_99mb_file_passes_100mb_limit(self):
        """99MB file should pass with 100MB limit."""
        from app import validate_backup_file_size
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        # Create ~99MB file (slightly under to avoid padding overhead)
        filepath = create_test_backup_file(content, size_mb=98.5)
        
        try:
            is_valid, error = validate_backup_file_size(filepath, max_size_mb=100)
            assert is_valid, f"99MB file should pass 100MB limit: {error}"
        finally:
            os.unlink(filepath)
    
    def test_101mb_file_rejected_100mb_limit(self):
        """101MB file should be rejected with 100MB limit."""
        from app import validate_backup_file_size
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        # Create ~101MB file
        filepath = create_test_backup_file(content, size_mb=101)
        
        try:
            is_valid, error = validate_backup_file_size(filepath, max_size_mb=100)
            assert not is_valid, "101MB file should be rejected with 100MB limit"
            assert error and "exceeds" in error and "100" in error
        finally:
            os.unlink(filepath)


class TestIntegrationValidation:
    """Test combined validation scenarios."""
    
    def test_multiple_issues_detected(self):
        """File with multiple issues should report first issue found."""
        from app import validate_backup_file_security
        from app import validate_schema_integrity
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\nCREATE TABLE `evil_table` (id INT);\n"
        content += "\nGRANT ALL PRIVILEGES ON *.* TO 'attacker'@'%';\n"
        filepath = create_test_backup_file(content)
        
        try:
            # Should catch GRANT statement
            is_secure, security_error = validate_backup_file_security(filepath)
            assert not is_secure, "Security issues should be detected"
            
            # Should also catch unexpected table
            is_valid_schema, schema_error = validate_schema_integrity(filepath)
            assert not is_valid_schema, "Schema issues should be detected"
        finally:
            os.unlink(filepath)
    
    def test_validation_with_comments(self):
        """Comments should not trigger false positives."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER
        content += "-- This comment mentions GRANT but is harmless\n"
        content += "/* Multi-line comment with GRANT keyword */\n"
        content += VALID_TABLE_STRUCTURE
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert is_valid, f"Comments should not trigger validation: {error}"
        finally:
            os.unlink(filepath)
    
    def test_case_insensitive_detection(self):
        """Pattern detection should be case-insensitive."""
        from app import validate_backup_file_security
        
        content = VALID_BACKUP_HEADER + VALID_TABLE_STRUCTURE
        content += "\ngrant all privileges on *.* to 'attacker'@'%';\n"
        filepath = create_test_backup_file(content)
        
        try:
            is_valid, error = validate_backup_file_security(filepath)
            assert not is_valid, "Lowercase GRANT should be detected"
        finally:
            os.unlink(filepath)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

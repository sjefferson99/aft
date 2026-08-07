"""Security and payload validation helpers."""

import os
import re


def validate_safe_url(url):
    """Validate that a URL uses a safe protocol."""
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    url = url.strip()
    url_lower = url.lower()

    dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:', 'about:', 'blob:']
    for protocol in dangerous_protocols:
        if url_lower.startswith(protocol):
            return False, f"URL protocol '{protocol}' is not allowed for security reasons"

    unsafe_attribute_chars = ['"', "'", '<', '>', '`']
    if any(char in url for char in unsafe_attribute_chars):
        return False, "URL contains unsafe characters"

    if any(char in url for char in ['\r', '\n', '\t']):
        return False, "URL contains disallowed control characters"

    if url_lower.startswith('/'):
        return True, None

    if url_lower.startswith('http://') or url_lower.startswith('https://'):
        return True, None

    return False, "URL must be a relative path starting with / or use http:// or https:// protocol"


def validate_backup_file_security(file_path):
    """Validate backup file for dangerous SQL patterns."""
    # Patterns anchored to the start of a statement (start of line, or
    # immediately after a `;` statement separator, optionally with leading
    # whitespace) so they only match actual SQL statements — not occurrences
    # of these words inside quoted data values (e.g. an INSERT row containing
    # the text "Prepare flower bed") — while still catching a dangerous
    # statement smuggled after a leading throwaway statement on the same
    # line (e.g. "SELECT 1; GRANT ALL PRIVILEGES ON *.* TO 'x'@'%';").
    STMT_START = r'(?:^|;)\s*'
    dangerous_patterns = [
        (STMT_START + r'GRANT\s+', 'GRANT statements (privilege manipulation)'),
        (STMT_START + r'CREATE\s+USER\b', 'CREATE USER statements'),
        (STMT_START + r'DROP\s+USER\b', 'DROP USER statements'),
        (STMT_START + r'ALTER\s+USER\b', 'ALTER USER statements'),
        (r'\bINTO\s+OUTFILE\b', 'INTO OUTFILE (file system access)'),
        (STMT_START + r'LOAD\s+DATA\b', 'LOAD DATA (file system access)'),
        (STMT_START + r'CREATE\s+(PROCEDURE|FUNCTION)\b', 'Stored procedures/functions'),
        (STMT_START + r'USE\s+[`\']?\w+[`\']?\s*;', 'USE statements (cross-database operation)'),
        (r'\\!', 'MySQL shell commands'),
        (r'\bSELECT\s+.+?\bINTO\s+@', 'Variable assignment with SELECT'),
        (STMT_START + r'EXECUTE\s+', 'Dynamic SQL execution'),
        (STMT_START + r'PREPARE\s+', 'Prepared statement (potential SQL injection)'),
    ]

    try:
        line_num = 0
        in_multiline_comment = False

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line_num += 1
                stripped = line.strip()

                if in_multiline_comment:
                    if '*/' in line:
                        in_multiline_comment = False
                        after_comment = line.split('*/', 1)[1].strip()
                        if not after_comment or after_comment.startswith('--'):
                            continue
                        stripped = after_comment
                    else:
                        continue

                if '/*' in stripped:
                    before_comment = stripped.split('/*', 1)[0].strip()
                    if '*/' in line:
                        after_comment = line.split('*/', 1)[1].strip()
                        stripped = before_comment + ' ' + after_comment
                    else:
                        in_multiline_comment = True
                        stripped = before_comment

                if not stripped or stripped.startswith('--'):
                    continue

                for pattern, description in dangerous_patterns:
                    if re.search(pattern, stripped, re.IGNORECASE):
                        return False, f"Dangerous SQL pattern detected on line {line_num}: {description}"

        return True, None
    except Exception as e:
        return False, f"Error reading backup file: {str(e)}"


def validate_schema_integrity(file_path, expected_tables=None):
    """Validate that backup only contains expected database tables."""
    if expected_tables is None:
        expected_tables = [
            'boards',
            'columns',
            'cards',
            'card_secondary_assignees',
            'board_settings',
            'checklist_items',
            'comments',
            'settings',
            'instance_config',
            'notifications',
            'scheduled_cards',
            'themes',
            'roles',
            'users',
            'user_roles',
            'alembic_version'
        ]

    found_tables = set()
    unexpected_tables = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                match = re.match(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"]?([^`"\s(]+)[`"]?', line, re.IGNORECASE)
                if match:
                    table_name = match.group(1)
                    found_tables.add(table_name)
                    if table_name not in expected_tables:
                        unexpected_tables.append(table_name)

        if unexpected_tables:
            return False, f"Unexpected tables found in backup: {', '.join(unexpected_tables)}"

        core_tables = {'boards', 'columns', 'cards'}
        if not core_tables.intersection(found_tables):
            return False, "Backup does not appear to contain valid AFT database schema"

        return True, None
    except Exception as e:
        return False, f"Error validating schema: {str(e)}"


def validate_backup_file_size(file_path, max_size_mb=100):
    """Validate backup file size to prevent DoS attacks."""
    try:
        file_size = os.path.getsize(file_path)
        max_size_bytes = max_size_mb * 1024 * 1024

        if file_size > max_size_bytes:
            size_mb = file_size / (1024 * 1024)
            return False, f"File size ({size_mb:.1f}MB) exceeds maximum allowed size ({max_size_mb}MB)"

        return True, None
    except Exception as e:
        return False, f"Error checking file size: {str(e)}"


def validate_json_import_payload_size(payload_text, max_size_mb=25):
    """Validate JSON import payload size before parsing."""
    try:
        payload_size = len(payload_text.encode('utf-8'))
        max_size_bytes = max_size_mb * 1024 * 1024
        if payload_size > max_size_bytes:
            size_mb = payload_size / (1024 * 1024)
            return False, f"Import file size ({size_mb:.1f}MB) exceeds maximum allowed size ({max_size_mb}MB)"
        return True, None
    except Exception as e:
        return False, f"Error checking import size: {str(e)}"

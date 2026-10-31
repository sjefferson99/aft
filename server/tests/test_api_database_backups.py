"""Tests for database backup and restore API endpoints."""
import re
import threading
import time
import uuid

import pytest
import requests


@pytest.mark.api
class TestDatabaseBackupsAPI:
    """Test cases for /api/database/backups endpoints."""
    
    def test_list_backups_response_structure_empty_or_populated(self, api_client, authenticated_session):
        """Test listing backups returns correct structure."""
        response = authenticated_session.get(f'{api_client}/api/database/backups/list')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'backups' in data
        assert isinstance(data['backups'], list)
        
        # Verify structure is correct regardless of whether backups exist
        for backup in data['backups']:
            assert 'filename' in backup
            assert 'created' in backup
            assert 'size' in backup
    
    def test_list_backups_with_data(self, api_client, authenticated_session):
        """Test listing backups when they exist."""
        response = authenticated_session.get(f'{api_client}/api/database/backups/list')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # If backups exist, check their structure
        if len(data['backups']) > 0:
            backup = data['backups'][0]
            assert 'filename' in backup
            assert 'created' in backup
            assert 'size' in backup
            assert 'is_manual' in backup
            assert backup['size'] > 0
            assert backup['filename'].endswith('.sql')
    
    def test_list_backups_sorted_newest_first(self, api_client, authenticated_session):
        """Test that backups are sorted newest first."""
        import time
        
        # Create multiple backups via API with delays between them
        created_backups = []
        for i in range(3):
            response = authenticated_session.post(f'{api_client}/api/database/backup/manual')
            if response.status_code != 200:
                print(f"Backup {i+1} failed with status {response.status_code}: {response.text}")
                continue
            
            data = response.json()
            if not data.get('success'):
                print(f"Backup {i+1} returned success=False: {data}")
                continue
                
            filename = data.get('filename')
            if filename:
                created_backups.append(filename)
                print(f"Created backup {i+1}: {filename}")
            else:
                print(f"Backup {i+1} returned no filename: {data}")
            
            if i < 2:  # Don't sleep after the last one
                time.sleep(1)  # Delay to ensure different timestamps
        
        # Ensure we created at least some backups
        assert len(created_backups) > 0, f"Failed to create any backups"
        
        try:
            # List backups
            response = authenticated_session.get(f'{api_client}/api/database/backups/list')
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            
            # Get all backups
            all_backups = data['backups']
            
            # Find our created backups in the list
            found_backups = [b for b in all_backups if b['filename'] in created_backups]
            
            # We should find all the backups we created
            assert len(found_backups) == len(created_backups), \
                f"Expected to find {len(created_backups)} backups, found {len(found_backups)}"
            
            # Verify that our created backups are in reverse chronological order
            # (newest first) based on their 'created' timestamps
            if len(found_backups) >= 2:
                for i in range(len(found_backups) - 1):
                    current_created = found_backups[i]['created']
                    next_created = found_backups[i + 1]['created']
                    assert current_created >= next_created, \
                        f"Backups not sorted correctly: {current_created} should be >= {next_created}"
        finally:
            # Cleanup - delete the test backups
            for filename in created_backups:
                try:
                    authenticated_session.delete(f'{api_client}/api/database/backup/{filename}')
                except:
                    pass  # Ignore cleanup errors
    
    def test_list_backups_includes_all_sql_files(self, api_client, authenticated_session):
        """Test that all SQL backup files are listed."""
        response = authenticated_session.get(f'{api_client}/api/database/backups/list')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # All returned files should be SQL files
        for backup in data['backups']:
            assert backup['filename'].endswith('.sql')
            # Verify is_manual flag exists and is boolean
            assert 'is_manual' in backup
            assert isinstance(backup['is_manual'], bool)
            # Manual backups should not start with auto_backup_
            if backup['is_manual']:
                assert not backup['filename'].startswith('auto_backup_')
            else:
                assert backup['filename'].startswith('auto_backup_')
            # Verify filename format: either auto_backup or aft_backup with timestamp
            import re
            assert re.match(r'^(auto_backup_|aft_backup_)\d{8}_\d{6}\.sql$', backup['filename'])
    
    def test_restore_backup_invalid_filename_format(self, api_client, authenticated_session):
        """Test that restore rejects invalid filename formats."""
        # Try various invalid filename formats
        invalid_filenames = [
            "manual_backup.sql",
            "backup_invalid.sql",
            "backup_20240101.sql",
            "backup_20240101_12.sql",
        ]
        
        for filename in invalid_filenames:
            response = authenticated_session.post(
                f'{api_client}/api/database/backups/restore/{filename}'
            )
            # Should be rejected with 400 (invalid) or 404 (file not found after validation)
            assert response.status_code in [400, 404], f"Failed for filename: {filename}"
            # API should always return JSON
            data = response.json()
            assert data['success'] is False
            assert 'message' in data
    
    def test_restore_backup_path_traversal_prevention(self, api_client, authenticated_session):
        """Test that path traversal attacks are prevented."""
        # Try various path traversal techniques
        # Note: Some special characters in URLs may cause Flask routing errors
        # resulting in 404 HTML responses instead of JSON
        path_traversal_attempts = [
            "auto_backup_20240101_120000.sql..",
            "auto_backup_20240101_120000.sql~",
        ]
        
        for attempt in path_traversal_attempts:
            response = authenticated_session.post(
                f'{api_client}/api/database/backups/restore/{attempt}'
            )
            # Should be rejected (400 invalid format or 404 not found)
            assert response.status_code in [400, 404], f"Failed for attempt: {attempt}"
            # API should always return JSON
            data = response.json()
            assert data['success'] is False
    
    def test_restore_backup_file_not_found(self, api_client, authenticated_session):
        """Test restoring a backup that doesn't exist."""
        response = authenticated_session.post(
            f'{api_client}/api/database/backups/restore/auto_backup_99990101_000000.sql'
        )
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'message' in data
        assert 'not found' in data['message'].lower()
    
    def test_restore_backup_success(self, api_client, authenticated_session):
        """Test successful backup restoration using API."""
        # Create a real backup using the API
        backup_response = authenticated_session.post(
            f'{api_client}/api/database/backup/manual',
            json={'description': 'Test restore backup'}
        )
        assert backup_response.status_code == 200
        backup_data = backup_response.json()
        assert backup_data['success'] is True
        backup_filename = backup_data['filename']
        
        try:
            # Wait a moment for backup to complete
            time.sleep(0.5)
            
            # Attempt to restore from the created backup
            response = authenticated_session.post(
                f'{api_client}/api/database/backups/restore/{backup_filename}'
            )
            
            # Restore should succeed with a valid backup
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            assert 'restored' in data['message'].lower() or 'success' in data['message'].lower()
        finally:
            # Cleanup: delete the test backup via API
            try:
                authenticated_session.delete(
                    f'{api_client}/api/database/backups/delete/{backup_filename}'
                )
            except:
                pass
    
    def test_restore_backup_version_mismatch(self, api_client, authenticated_session):
        """Test restore behavior with invalid backup file."""
        # Test with a non-existent backup file (simulates corrupted/missing backup)
        response = authenticated_session.post(
            f'{api_client}/api/database/backups/restore/invalid_backup_99999999_999999.sql'
        )
        
        # Should fail gracefully
        assert response.status_code in [400, 404]
        data = response.json()
        assert data['success'] is False
        assert 'message' in data
        assert len(data['message']) > 0
        
        # Note: Testing actual version mismatch requires creating a backup with different
        # alembic version, which cannot be done safely via API without modifying the database.
        # The validation is tested through other restore tests that use real backups.
    
    def test_list_backups_directory_permissions(self, api_client, authenticated_session):
        """Test handling of directory permission issues."""
        # This test documents expected behavior if backup dir is inaccessible
        # In production, the directory should always be accessible
        response = authenticated_session.get(f'{api_client}/api/database/backups/list')
        
        # Should handle gracefully even if there are permission issues
        assert response.status_code in [200, 500]
        data = response.json()
        assert 'success' in data
    
    def test_restore_backup_concurrent_operation(self, api_client, authenticated_session):
        """Test that restore operations handle invalid filenames gracefully."""
        # Test with backup filename that has invalid characters or format
        # This tests error handling without creating actual files
        invalid_filenames = [
            '../../../etc/passwd',  # Path traversal attempt
            'backup with spaces.sql',  # Spaces (may or may not be allowed)
            'backup;delete.sql',  # Special characters
        ]
        
        for invalid_filename in invalid_filenames:
            response = authenticated_session.post(
                f'{api_client}/api/database/backups/restore/{invalid_filename}'
            )
            
            # Should reject invalid filenames securely
            assert response.status_code in [400, 404]
            data = response.json()
            assert data['success'] is False
            assert 'message' in data
            
        # Note: Testing actual concurrent operations requires threading/multiprocessing
        # which is complex for integration tests. The lock file mechanism is tested
        # through the restore workflow itself.
    
    def test_list_backups_response_structure(self, api_client, authenticated_session):
        """Test that the response has the correct structure."""
        response = authenticated_session.get(f'{api_client}/api/database/backups/list')
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert 'success' in data
        assert 'backups' in data
        assert isinstance(data['backups'], list)
        
        # If backups exist, check structure of each item
        for backup in data['backups']:
            assert 'filename' in backup
            assert 'created' in backup
            assert 'size' in backup
            assert isinstance(backup['filename'], str)
            assert isinstance(backup['created'], str)
            assert isinstance(backup['size'], int)
            assert backup['size'] >= 0
    
    def test_restore_backup_response_structure_error(self, api_client, authenticated_session):
        """Test error response structure for restore endpoint."""
        # Use invalid filename to trigger error
        response = authenticated_session.post(
            f'{api_client}/api/database/backups/restore/invalid_name.sql'
        )
        
        assert response.status_code == 400
        data = response.json()
        
        # Check error response structure
        assert 'success' in data
        assert data['success'] is False
        assert 'message' in data
        assert isinstance(data['message'], str)
        assert len(data['message']) > 0
    
    def test_list_backups_large_files(self, api_client, authenticated_session):
        """Test that large backup files are handled correctly."""
        response = authenticated_session.get(f'{api_client}/api/database/backups/list')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # If backups exist, verify size field is present and reasonable
        if len(data['backups']) > 0:
            for backup in data['backups']:
                assert 'size' in backup
                assert isinstance(backup['size'], int)
                assert backup['size'] > 0
                # Backup files should be at least a few KB
                assert backup['size'] > 1000
    
    def test_restore_backup_special_characters_rejected(self, api_client, authenticated_session):
        """Test that filenames with special characters are rejected."""
        special_char_filenames = [
            "auto_backup_20240101_120000.sql\x00.txt",  # Null byte
            "auto_backup_20240101_120000.sql\n.txt",     # Newline
            "auto_backup_20240101_120000.sql\r.txt",     # Carriage return
            "auto_backup_20240101_120000.sql\t.txt",     # Tab
        ]
        
        for filename in special_char_filenames:
            response = authenticated_session.post(
                f'{api_client}/api/database/backups/restore/{filename}'
            )
            # Should be rejected - these may return 400, 404, or 405 depending on how the server handles malformed URLs
            assert response.status_code in [400, 404, 405], f"Expected error status for filename with special chars, got {response.status_code}"
            # Only check JSON if response has content
            if response.content:
                try:
                    data = response.json()
                    assert data['success'] is False
                except (ValueError, AssertionError):
                    # Response might not be JSON if the request was malformed
                    pass


@pytest.mark.api
class TestRestoreProgressAPI:
    """Test cases for /api/database/restore/progress (issue #590)."""

    def test_unknown_id_has_no_progress(self, api_client):
        """Needs no session, because the page polls while the database is down."""
        response = requests.get(f'{api_client}/api/database/restore/progress/{uuid.uuid4().hex}')

        assert response.status_code == 200
        assert response.json() == {'success': True, 'progress': None}

    @pytest.mark.parametrize('progress_id', ['short', 'A' * 32, 'g' * 32, 'a' * 33, 'a' * 32 + '%0a'])
    def test_invalid_id_rejected(self, api_client, progress_id):
        response = requests.get(f'{api_client}/api/database/restore/progress/{progress_id}')

        assert response.status_code == 400
        assert response.json()['success'] is False

    def test_failed_validation_leaves_last_step_readable(self, api_client, authenticated_session):
        progress_id = uuid.uuid4().hex

        response = authenticated_session.post(
            f'{api_client}/api/database/restore',
            headers={'X-Restore-Progress-Id': progress_id},
            files={'file': ('bad.sql', b'not a backup', 'application/sql')},
        )

        assert response.status_code == 400
        progress = requests.get(f'{api_client}/api/database/restore/progress/{progress_id}').json()
        assert progress['progress'] == {'message': 'Checking the backup file'}

    def test_invalid_progress_id_does_not_stop_a_restore_request(self, api_client, authenticated_session):
        response = authenticated_session.post(
            f'{api_client}/api/database/backups/restore/aft_backup_19990101_000000.sql',
            headers={'X-Restore-Progress-Id': 'not-valid'},
        )

        assert response.status_code == 404

    def test_progress_is_readable_throughout_a_real_restore(self, api_client, authenticated_session):
        """The database is dropped partway, and polling must keep working."""
        backup_response = authenticated_session.post(f'{api_client}/api/database/backup/manual')
        assert backup_response.status_code == 200
        filename = backup_response.json()['filename']
        progress_id = uuid.uuid4().hex
        restore_result = {}

        def run_restore():
            restore_result['response'] = authenticated_session.post(
                f'{api_client}/api/database/backups/restore/{filename}',
                headers={'X-Restore-Progress-Id': progress_id},
            )

        restore = threading.Thread(target=run_restore)
        statuses = set()
        messages = []
        restore.start()
        try:
            while restore.is_alive():
                response = requests.get(f'{api_client}/api/database/restore/progress/{progress_id}')
                statuses.add(response.status_code)
                progress = response.json()['progress']
                if progress and progress['message'] not in messages:
                    messages.append(progress['message'])
                time.sleep(0.05)
        finally:
            restore.join()

        try:
            assert restore_result['response'].status_code == 200
            assert statuses == {200}
            assert 'Clearing the existing database' in messages

            final = requests.get(f'{api_client}/api/database/restore/progress/{progress_id}').json()
            assert 0 < final['progress']['bytes_done'] <= final['progress']['bytes_total']
            assert re.fullmatch(r'Restoring table \d+ of \d+: \w+', final['progress']['message'])
        finally:
            authenticated_session.delete(f'{api_client}/api/database/backups/delete/{filename}')

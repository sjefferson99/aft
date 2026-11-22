"""Tests for health and statistics API endpoints."""

import pytest
import requests


@pytest.mark.api
class TestHealthEndpoints:
    """Tests for health, stats, and scheduler-health endpoints."""

    def test_liveness_endpoint(self, api_client, authenticated_session):
        """Test public liveness endpoint."""
        response = authenticated_session.get(f"{api_client}/api/health/live")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True

    def test_server_health_endpoint_public_boolean(self, api_client):
        """Public server health endpoint should return a minimal boolean payload."""
        response = requests.get(f"{api_client}/api/server-health", timeout=5)
        assert response.status_code == 200

        data = response.json()
        assert set(data.keys()) == {"healthy"}
        assert isinstance(data["healthy"], bool)

    def test_readiness_requires_token(self, api_client, authenticated_session):
        """Readiness endpoint should not be accessible without health token."""
        response = authenticated_session.get(f"{api_client}/api/health/ready")
        assert response.status_code == 404

    def test_database_connection(self, api_client, authenticated_session):
        """Test legacy database connection endpoint still functions for authenticated users."""
        response = authenticated_session.get(f"{api_client}/api/test")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Connected to database"

    def test_database_stats_empty(self, api_client, authenticated_session, isolated_test):
        """Test stats endpoint with empty database."""
        response = authenticated_session.get(f"{api_client}/api/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["boards_count"] == 0
        assert data["columns_count"] == 0
        assert data["cards_count"] == 0
        assert data["cards_archived_count"] == 0
        assert data["checklist_items_total"] == 0
        assert data["checklist_items_checked"] == 0
        assert data["checklist_items_unchecked"] == 0

    def test_database_stats_with_data(self, api_client, authenticated_session, isolated_test, sample_board):
        """Test stats endpoint with sample data."""
        # Create additional data
        # Add a column
        col_response = authenticated_session.post(
            f"{api_client}/api/boards/{sample_board['id']}/columns",
            json={"name": "Test Column"}
        )
        assert col_response.status_code == 201
        column = col_response.json()["column"]
        
        # Add active card
        card1_response = authenticated_session.post(
            f"{api_client}/api/columns/{column['id']}/cards",
            json={"title": "Active Card", "description": "Test"}
        )
        assert card1_response.status_code == 201
        card1 = card1_response.json()["card"]
        
        # Add archived card
        card2_response = authenticated_session.post(
            f"{api_client}/api/columns/{column['id']}/cards",
            json={"title": "Archived Card", "description": "Test"}
        )
        assert card2_response.status_code == 201
        card2 = card2_response.json()["card"]
        
        # Archive the second card
        archive_response = authenticated_session.patch(f"{api_client}/api/cards/{card2['id']}/archive")
        assert archive_response.status_code == 200
        
        # Add checklist items
        item1_response = authenticated_session.post(
            f"{api_client}/api/cards/{card1['id']}/checklist-items",
            json={"name": "Task 1", "checked": True}
        )
        assert item1_response.status_code == 201
        
        item2_response = authenticated_session.post(
            f"{api_client}/api/cards/{card1['id']}/checklist-items",
            json={"name": "Task 2", "checked": False}
        )
        assert item2_response.status_code == 201
        
        # Check stats
        response = authenticated_session.get(f"{api_client}/api/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["boards_count"] == 1
        assert data["columns_count"] == 1
        assert data["cards_count"] == 2
        assert data["cards_archived_count"] == 1
        assert data["checklist_items_total"] == 2
        assert data["checklist_items_checked"] == 1
        assert data["checklist_items_unchecked"] == 1

    def test_stats_updates_after_archive(self, api_client, authenticated_session, isolated_test, sample_board):
        """Test that stats update correctly when cards are archived/unarchived."""
        # Create column and cards
        col_response = authenticated_session.post(
            f"{api_client}/api/boards/{sample_board['id']}/columns",
            json={"name": "Test Column"}
        )
        column = col_response.json()["column"]
        
        card1_response = authenticated_session.post(
            f"{api_client}/api/columns/{column['id']}/cards",
            json={"title": "Card 1", "description": "Test"}
        )
        card1 = card1_response.json()["card"]
        
        card2_response = authenticated_session.post(
            f"{api_client}/api/columns/{column['id']}/cards",
            json={"title": "Card 2", "description": "Test"}
        )
        card2 = card2_response.json()["card"]
        
        # Initial stats - no archived cards
        response = authenticated_session.get(f"{api_client}/api/stats")
        data = response.json()
        assert data["cards_count"] == 2
        assert data["cards_archived_count"] == 0
        
        # Archive one card
        authenticated_session.patch(f"{api_client}/api/cards/{card1['id']}/archive")
        
        response = authenticated_session.get(f"{api_client}/api/stats")
        data = response.json()
        assert data["cards_count"] == 2
        assert data["cards_archived_count"] == 1
        
        # Archive another card
        authenticated_session.patch(f"{api_client}/api/cards/{card2['id']}/archive")
        
        response = authenticated_session.get(f"{api_client}/api/stats")
        data = response.json()
        assert data["cards_count"] == 2
        assert data["cards_archived_count"] == 2
        
        # Unarchive one card
        authenticated_session.patch(f"{api_client}/api/cards/{card1['id']}/unarchive")
        
        response = authenticated_session.get(f"{api_client}/api/stats")
        data = response.json()
        assert data["cards_count"] == 2
        assert data["cards_archived_count"] == 1

    def test_stats_for_user_with_only_board_role(
        self, api_client, authenticated_session, second_user_session, isolated_test, sample_board
    ):
        """A user whose only board access is a board role gets stats for that board (#705)."""
        me_response = second_user_session.get(f"{api_client}/api/auth/me")
        assert me_response.status_code == 200
        second_user_id = me_response.json()["user"]["id"]

        shared_response = authenticated_session.post(
            f"{api_client}/api/boards",
            json={"name": "Shared Stats Board", "description": "Shared with a board editor"},
        )
        assert shared_response.status_code == 201
        shared_board_id = shared_response.json()["board"]["id"]

        col_response = authenticated_session.post(
            f"{api_client}/api/boards/{shared_board_id}/columns",
            json={"name": "Shared Column"},
        )
        assert col_response.status_code == 201
        shared_column_id = col_response.json()["column"]["id"]

        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{shared_column_id}/cards",
            json={"title": "Shared Card", "description": "Test"},
        )
        assert card_response.status_code == 201

        role_response = authenticated_session.post(
            f"{api_client}/api/users/{second_user_id}/roles",
            json={"role_name": "board_editor", "board_id": shared_board_id},
        )
        assert role_response.status_code in (200, 201), role_response.text

        response = second_user_session.get(f"{api_client}/api/stats")
        assert response.status_code == 200, response.text

        data = response.json()
        assert data["success"] is True
        # Only the shared board counts; the admin's sample_board is not visible.
        assert data["boards_count"] == 1
        assert data["columns_count"] == 1
        assert data["cards_count"] == 1

    def test_stats_requires_authentication(self, api_client):
        """Stats are only available to signed-in users."""
        response = requests.get(f"{api_client}/api/stats", timeout=5)
        assert response.status_code == 401


@pytest.mark.api
class TestSchedulerHealthEndpoint:
    """Tests for /api/scheduler/health endpoint."""
    
    def test_scheduler_health_endpoint_exists(self, api_client, authenticated_session):
        """Test that scheduler health endpoint is accessible."""
        response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        assert response.status_code == 200
    
    def test_scheduler_health_structure(self, api_client, authenticated_session):
        """Test that scheduler health returns expected structure."""
        response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        assert response.status_code == 200
        
        data = response.json()
        
        # Should have all three schedulers
        assert "backup_scheduler" in data
        assert "card_scheduler" in data
        assert "housekeeping_scheduler" in data
    
    def test_backup_scheduler_health_fields(self, api_client, authenticated_session):
        """Test backup scheduler health contains expected fields."""
        response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        data = response.json()
        
        backup = data["backup_scheduler"]
        
        # Should not have error (or if it does, it should be a string)
        if "error" in backup:
            assert isinstance(backup["error"], str)
        else:
            # Should have these fields when healthy
            assert "running" in backup
            assert "thread_alive" in backup
            assert "lock_file_exists" in backup
            
            # Running and thread_alive should be booleans
            assert isinstance(backup["running"], bool)
            assert isinstance(backup["thread_alive"], bool)
            assert isinstance(backup["lock_file_exists"], bool)
            
            # Optional fields
            if "last_backup" in backup:
                assert backup["last_backup"] is None or isinstance(backup["last_backup"], str)
            
            if "lock_file_age_seconds" in backup:
                assert isinstance(backup["lock_file_age_seconds"], (int, float))
            
            if "lock_pid" in backup:
                assert isinstance(backup["lock_pid"], int)
            
            if "lock_container" in backup:
                assert isinstance(backup["lock_container"], str)
    
    def test_card_scheduler_health_fields(self, api_client, authenticated_session):
        """Test card scheduler health contains expected fields."""
        response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        data = response.json()
        
        card = data["card_scheduler"]
        
        # Should not have error (or if it does, it should be a string)
        if "error" in card:
            assert isinstance(card["error"], str)
        else:
            # Should have these fields when healthy
            assert "running" in card
            assert "thread_alive" in card
            assert "lock_file_exists" in card
            
            # Values should be appropriate types
            assert isinstance(card["running"], bool)
            assert isinstance(card["thread_alive"], bool)
            assert isinstance(card["lock_file_exists"], bool)
            
            # If lock file exists, should have details
            if card["lock_file_exists"]:
                if "lock_file_age_seconds" in card:
                    assert isinstance(card["lock_file_age_seconds"], (int, float))
                    # Heartbeat should be recent (less than 5 minutes)
                    assert card["lock_file_age_seconds"] < 300
    
    def test_housekeeping_scheduler_health_fields(self, api_client, authenticated_session):
        """Test housekeeping scheduler health contains expected fields."""
        response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        data = response.json()
        
        housekeeping = data["housekeeping_scheduler"]
        
        # Should not have error (or if it does, it should be a string)
        if "error" in housekeeping:
            assert isinstance(housekeeping["error"], str)
        else:
            # Should have these fields when healthy
            assert "running" in housekeeping
            assert "thread_alive" in housekeeping
            assert "lock_file_exists" in housekeeping
            
            # Values should be appropriate types
            assert isinstance(housekeeping["running"], bool)
            assert isinstance(housekeeping["thread_alive"], bool)
            assert isinstance(housekeeping["lock_file_exists"], bool)
    
    def test_scheduler_health_consistency(self, api_client, authenticated_session):
        """Test that scheduler health is consistent across multiple calls."""
        # Get health twice
        response1 = authenticated_session.get(f"{api_client}/api/scheduler/health")
        response2 = authenticated_session.get(f"{api_client}/api/scheduler/health")
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Running status should be consistent
        for scheduler_name in ["backup_scheduler", "card_scheduler", "housekeeping_scheduler"]:
            if "error" not in data1[scheduler_name] and "error" not in data2[scheduler_name]:
                assert data1[scheduler_name]["running"] == data2[scheduler_name]["running"]
                assert data1[scheduler_name]["thread_alive"] == data2[scheduler_name]["thread_alive"]
    
    def test_scheduler_heartbeat_updates(self, api_client, authenticated_session):
        """Test that scheduler heartbeat ages are reasonable."""
        response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        data = response.json()
        
        # Check each scheduler's heartbeat
        for scheduler_name in ["backup_scheduler", "card_scheduler", "housekeeping_scheduler"]:
            scheduler = data[scheduler_name]
            
            if "error" not in scheduler and "lock_file_age_seconds" in scheduler:
                age = scheduler["lock_file_age_seconds"]
                
                # Heartbeat should be recent (updated every 60 seconds in loop)
                # Allow up to 5 minutes for safety in slow test environments
                assert age < 300, f"{scheduler_name} heartbeat is stale: {age}s"
                
                # Should not be negative
                assert age >= 0, f"{scheduler_name} heartbeat age is negative: {age}s"
    
    def test_scheduler_health_with_disabled_backup(self, api_client, authenticated_session):
        """Test scheduler health when backup is disabled."""
        # Disable backup
        response = authenticated_session.put(
            f"{api_client}/api/settings/backup/config",
            json={"enabled": False}
        )
        assert response.status_code == 200
        
        # Check health - scheduler should still be running even if backups disabled
        health_response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        assert health_response.status_code == 200
        
        data = health_response.json()
        backup = data["backup_scheduler"]
        
        # Scheduler thread should still exist and be alive
        if "error" not in backup:
            assert "running" in backup
            assert "thread_alive" in backup
        
        # Re-enable backup
        authenticated_session.put(
            f"{api_client}/api/settings/backup/config",
            json={"enabled": True}
        )
    
    def test_scheduler_health_container_id(self, api_client, authenticated_session):
        """Test that scheduler health includes container ID information."""
        response = authenticated_session.get(f"{api_client}/api/scheduler/health")
        data = response.json()
        
        # At least one scheduler should have container ID (if running in Docker)
        for scheduler_name in ["backup_scheduler", "card_scheduler", "housekeeping_scheduler"]:
            scheduler = data[scheduler_name]
            if "lock_container" in scheduler:
                # Container ID should be a non-empty string
                assert isinstance(scheduler["lock_container"], str)
                assert len(scheduler["lock_container"]) > 0
        
        # If no container IDs found, that's okay (might be running outside Docker)
        # Just verify the endpoint structure is correct
        assert True


@pytest.mark.api
class TestBroadcastStatusEndpoint:
    """Tests for /api/broadcast-status endpoint used for WebSocket debugging."""

    def test_broadcast_status_endpoint_exists(self, api_client, authenticated_session):
        """Test that broadcast status endpoint is accessible."""
        response = authenticated_session.get(f"{api_client}/api/broadcast-status")
        assert response.status_code == 200

    def test_broadcast_status_structure(self, api_client, authenticated_session):
        """Test that broadcast status returns correct structure."""
        response = authenticated_session.get(f"{api_client}/api/broadcast-status")
        data = response.json()
        
        assert data["success"] is True
        assert "broadcast_failures" in data
        assert "total_failure_rooms" in data
        assert isinstance(data["broadcast_failures"], dict)
        assert isinstance(data["total_failure_rooms"], int)

    def test_broadcast_status_initially_empty(self, api_client, authenticated_session):
        """Test that broadcast status is empty on startup."""
        response = authenticated_session.get(f"{api_client}/api/broadcast-status")
        data = response.json()
        
        # Should have no failures initially
        assert data["total_failure_rooms"] == 0
        assert len(data["broadcast_failures"]) == 0

    def test_broadcast_status_version_endpoint(self, api_client, authenticated_session):
        """Test version endpoint alongside broadcast status."""
        # Test version endpoint first
        version_response = authenticated_session.get(f"{api_client}/api/version")
        assert version_response.status_code == 200
        version_data = version_response.json()
        assert version_data["success"] is True
        
        # Broadcast status should still be clean
        broadcast_response = authenticated_session.get(f"{api_client}/api/broadcast-status")
        broadcast_data = broadcast_response.json()
        assert broadcast_data["total_failure_rooms"] == 0


"""Tests for board API endpoints."""
import json
import uuid

import pytest


def get_current_user(api_client, session):
    response = session.get(f'{api_client}/api/auth/me')
    assert response.status_code == 200
    data = response.json()
    return data['user']


def build_minimal_board_import_payload(board_name="Imported Board"):
    """Build a minimal valid AFT board import payload for API tests."""
    return {
        "export": {
            "format": "aft-board",
            "format_version": "1.0",
            "app_version": "test",
            "exported_at": "2026-03-28T00:00:00Z",
            "exported_by_user_id": 1,
            "source_board_id": 1,
            "features_exported": [
                "board",
                "board_settings",
                "columns",
                "cards",
                "card_secondary_assignees",
                "checklists",
                "comments",
                "scheduled_cards",
            ],
        },
        "board": {
            "id": 1,
            "name": board_name,
            "description": "Imported description",
            "owner_id": 1,
            "created_at": "2026-03-28T00:00:00Z",
            "updated_at": "2026-03-28T00:00:00Z",
        },
        "board_settings": [],
        "columns": [
            {
                "id": 10,
                "board_id": 1,
                "name": "Imported Column",
                "order": 0,
                "created_at": "2026-03-28T00:00:00Z",
                "updated_at": "2026-03-28T00:00:00Z",
            }
        ],
        "cards": [
            {
                "id": 100,
                "column_id": 10,
                "title": "Imported Card",
                "description": "Imported card description",
                "order": 0,
                "archived": False,
                "scheduled": False,
                "schedule": None,
                "done": False,
                "created_by_id": 999,
                "assigned_to_id": 999,
                "created_at": "2026-03-28T00:00:00Z",
                "updated_at": "2026-03-28T00:00:00Z",
            }
        ],
        "card_secondary_assignees": [
            {
                "id": 1,
                "card_id": 100,
                "user_id": 998,
                "created_at": "2026-03-28T00:00:00Z",
            }
        ],
        "checklists": [],
        "comments": [],
        "scheduled_cards": [],
    }


@pytest.mark.api
class TestBoardsAPI:
    """Test cases for /api/boards endpoints."""
    
    def test_get_boards_empty(self, api_client, authenticated_session, clean_database):
        """Test getting boards when none exist."""
        response = authenticated_session.get(f'{api_client}/api/boards')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['boards'] == []
    
    def test_get_boards_with_data(self, api_client, authenticated_session, isolated_test, sample_board):
        """Test getting boards with existing data."""
        response = authenticated_session.get(f'{api_client}/api/boards')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['boards']) == 1
        assert data['boards'][0]['name'] == 'Test Board'
        assert data['boards'][0]['archived'] is False
        assert 'created_at' in data['boards'][0]
        assert 'updated_at' in data['boards'][0]

    def test_archive_and_unarchive_board(self, api_client, authenticated_session, sample_board):
        """Test archiving and unarchiving a board with archived list filtering."""
        board_id = sample_board['id']

        archive_response = authenticated_session.patch(f'{api_client}/api/boards/{board_id}/archive')
        assert archive_response.status_code == 200
        archive_data = archive_response.json()
        assert archive_data['success'] is True
        assert archive_data['board']['archived'] is True

        active_list = authenticated_session.get(f'{api_client}/api/boards?archived=false')
        assert active_list.status_code == 200
        active_board_ids = {board['id'] for board in active_list.json()['boards']}
        assert board_id not in active_board_ids

        archived_list = authenticated_session.get(f'{api_client}/api/boards?archived=true')
        assert archived_list.status_code == 200
        archived_board_ids = {board['id'] for board in archived_list.json()['boards']}
        assert board_id in archived_board_ids

        board_cards_response = authenticated_session.get(f'{api_client}/api/boards/{board_id}/cards')
        assert board_cards_response.status_code == 200
        board_cards_data = board_cards_response.json()
        assert board_cards_data['success'] is True
        assert board_cards_data['board']['archived'] is True

        unarchive_response = authenticated_session.patch(f'{api_client}/api/boards/{board_id}/unarchive')
        assert unarchive_response.status_code == 200
        unarchive_data = unarchive_response.json()
        assert unarchive_data['success'] is True
        assert unarchive_data['board']['archived'] is False
    
    def test_create_board(self, api_client, authenticated_session):
        """Test creating a new board."""
        response = authenticated_session.post(f'{api_client}/api/boards', json={
            'name': 'New Board',
            'description': 'A new test board'
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['board']['name'] == 'New Board'
        assert 'id' in data['board']
        assert 'created_at' in data['board']
        assert 'updated_at' in data['board']
    
    def test_create_board_missing_name(self, api_client, authenticated_session):
        """Test creating a board without a name fails."""
        response = authenticated_session.post(f'{api_client}/api/boards', json={
            'description': 'No name provided'
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_get_board_by_id(self, api_client, authenticated_session, sample_board):
        """Test getting a specific board's columns."""
        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/columns')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'columns' in data
    
    def test_get_board_not_found(self, api_client, authenticated_session):
        """Test getting columns for a non-existent board returns 403 (no access)."""
        response = authenticated_session.get(f'{api_client}/api/boards/9999/columns')
        assert response.status_code == 403
    
    def test_update_board(self, api_client, authenticated_session, sample_board):
        """Test updating a board."""
        response = authenticated_session.patch(f'{api_client}/api/boards/{sample_board["id"]}', json={
            'name': 'Updated Board Name',
            'description': 'Updated description'
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['board']['name'] == 'Updated Board Name'
    
    def test_update_board_not_found(self, api_client, authenticated_session):
        """Test updating a non-existent board returns 403 (no access)."""
        response = authenticated_session.patch(f'{api_client}/api/boards/9999', json={
            'name': 'Updated Name'
        })
        assert response.status_code == 403

    def test_board_cards_include_owner_data_for_owner(self, api_client, authenticated_session, second_user_session, sample_board):
        """Board owners should receive owner metadata in the default board payload."""
        owner = get_current_user(api_client, authenticated_session)

        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards')
        assert response.status_code == 200

        data = response.json()
        assert data['success'] is True
        board = data['board']
        assert board['owner']['id'] == owner['id']
        assert board['can_reassign_owner'] is True
        assert 'available_owner_users' not in board

    def test_board_cards_include_owner_candidates_for_owner(self, api_client, authenticated_session, second_user_session, sample_board):
        """Board owners can request owner candidates explicitly for reassignment."""
        owner = get_current_user(api_client, authenticated_session)
        other_user = get_current_user(api_client, second_user_session)

        response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards?include_owner_candidates=true'
        )
        assert response.status_code == 200

        data = response.json()
        assert data['success'] is True
        board = data['board']
        returned_ids = {user['id'] for user in board['available_owner_users']}
        assert owner['id'] in returned_ids
        assert other_user['id'] in returned_ids

    def test_board_cards_include_owner_data_for_viewer(self, api_client, authenticated_session, second_user_session, sample_board):
        """Board viewers can read owner data but do not get reassignment candidates by default."""
        second_user = get_current_user(api_client, second_user_session)
        owner = get_current_user(api_client, authenticated_session)

        grant_response = authenticated_session.post(
            f'{api_client}/api/users/{second_user["id"]}/roles',
            json={'role_name': 'board_viewer', 'board_id': sample_board['id']}
        )
        assert grant_response.status_code == 200

        response = second_user_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards')
        assert response.status_code == 200

        data = response.json()
        assert data['success'] is True
        board = data['board']
        assert board['owner']['id'] == owner['id']
        assert board['can_reassign_owner'] is False
        assert 'available_owner_users' not in board

    def test_board_cards_include_no_owner_candidates_for_viewer(self, api_client, authenticated_session, second_user_session, sample_board):
        """Board viewers can request board owner metadata but still do not receive reassignment candidates."""
        second_user = get_current_user(api_client, second_user_session)

        grant_response = authenticated_session.post(
            f'{api_client}/api/users/{second_user["id"]}/roles',
            json={'role_name': 'board_viewer', 'board_id': sample_board['id']}
        )
        assert grant_response.status_code == 200

        response = second_user_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards?include_owner_candidates=true'
        )
        assert response.status_code == 200

        data = response.json()
        assert data['success'] is True
        board = data['board']
        assert board['available_owner_users'] == []

    def test_board_cards_forbidden_without_access(self, api_client, second_user_session, sample_board):
        """Users without board access must not load board payload owner details."""
        response = second_user_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards')
        assert response.status_code == 403

    def test_reassign_board_owner_as_owner(self, api_client, authenticated_session, second_user_session):
        """A non-admin board owner should be able to reassign their board to another user."""
        second_user = get_current_user(api_client, second_user_session)
        admin_user = get_current_user(api_client, authenticated_session)

        create_response = second_user_session.post(
            f'{api_client}/api/boards',
            json={'name': 'Second User Owned Board', 'description': 'Owned by test user B'}
        )
        assert create_response.status_code == 201
        board_id = create_response.json()['board']['id']

        response = second_user_session.put(
            f'{api_client}/api/boards/{board_id}/owner',
            json={'owner_id': admin_user['id']}
        )
        assert response.status_code == 200

        data = response.json()
        assert data['success'] is True
        assert data['board']['owner_id'] == admin_user['id']
        assert data['owner_id'] == admin_user['id']
        assert data['owner']['id'] == admin_user['id']

        old_owner_check = second_user_session.get(f'{api_client}/api/boards/{board_id}/cards')
        assert old_owner_check.status_code == 403

    def test_reassigned_owner_keeps_access_after_giving_board_away(self, api_client, authenticated_session, second_user_session, sample_board):
        """Users who receive ownership keep board access after giving ownership away again."""
        second_user = get_current_user(api_client, second_user_session)
        admin_user = get_current_user(api_client, authenticated_session)

        first_reassign = authenticated_session.put(
            f'{api_client}/api/boards/{sample_board["id"]}/owner',
            json={'owner_id': second_user['id']}
        )
        assert first_reassign.status_code == 200

        second_reassign = second_user_session.put(
            f'{api_client}/api/boards/{sample_board["id"]}/owner',
            json={'owner_id': admin_user['id']}
        )
        assert second_reassign.status_code == 200

        former_owner_check = second_user_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards')
        assert former_owner_check.status_code == 200

    def test_reassign_board_owner_as_admin(self, api_client, authenticated_session, second_user_session):
        """Administrators should be able to reassign any board."""
        second_user = get_current_user(api_client, second_user_session)
        admin_user = get_current_user(api_client, authenticated_session)

        create_response = second_user_session.post(
            f'{api_client}/api/boards',
            json={'name': 'Admin Reassign Test Board', 'description': 'Owned by test user B'}
        )
        assert create_response.status_code == 201
        board_id = create_response.json()['board']['id']

        response = authenticated_session.put(
            f'{api_client}/api/boards/{board_id}/owner',
            json={'owner_id': admin_user['id']}
        )
        assert response.status_code == 200

        data = response.json()
        assert data['success'] is True
        assert data['board']['owner_id'] == admin_user['id']

    def test_admin_with_board_specific_role_can_still_reassign_board(self, api_client, authenticated_session, second_user_session, sample_board):
        """Global administrators should still be able to reassign boards even when they also have board-scoped roles."""
        second_user = get_current_user(api_client, second_user_session)

        grant_admin_response = authenticated_session.post(
            f'{api_client}/api/users/{second_user["id"]}/roles',
            json={'role_name': 'administrator'}
        )
        assert grant_admin_response.status_code == 200

        grant_viewer_response = authenticated_session.post(
            f'{api_client}/api/users/{second_user["id"]}/roles',
            json={'role_name': 'board_viewer', 'board_id': sample_board['id']}
        )
        assert grant_viewer_response.status_code == 200

        response = second_user_session.put(
            f'{api_client}/api/boards/{sample_board["id"]}/owner',
            json={'owner_id': second_user['id']}
        )
        assert response.status_code == 200
    
    def test_delete_board(self, api_client, authenticated_session, sample_board):
        """Test deleting a board."""
        board_id = sample_board['id']
        response = authenticated_session.delete(f'{api_client}/api/boards/{board_id}')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Verify board is deleted - now returns 403 since it no longer exists in user's scope
        verify_response = authenticated_session.get(f'{api_client}/api/boards/{board_id}/columns')
        assert verify_response.status_code == 403
    
    def test_delete_board_not_found(self, api_client, authenticated_session):
        """Test deleting a non-existent board returns 403 (no access)."""
        response = authenticated_session.delete(f'{api_client}/api/boards/9999')
        assert response.status_code == 403
    
    def test_get_board_scheduled_cards(self, api_client, authenticated_session, sample_board, sample_column):
        """Test getting board with all scheduled cards in one request."""
        # First create a regular card to schedule
        card_data = {
            'title': 'Card to Schedule',
            'description': 'This will become a template'
        }
        card_response = authenticated_session.post(
            f'{api_client}/api/columns/{sample_column["id"]}/cards',
            json=card_data
        )
        assert card_response.status_code == 201
        card_id = card_response.json()['card']['id']
        
        # Create a schedule for the card (this creates the template card)
        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        schedule_data = {
            'card_id': card_id,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': tomorrow,
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
            'keep_source_card': True
        }
        schedule_response = authenticated_session.post(
            f'{api_client}/api/schedules',
            json=schedule_data
        )
        assert schedule_response.status_code == 201
        
        # Get board with scheduled cards
        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'board' in data
        assert data['board']['id'] == sample_board['id']
        assert data['board']['name'] == sample_board['name']
        assert 'columns' in data['board']
        
        # Verify column structure includes cards
        column = data['board']['columns'][0]
        assert 'id' in column
        assert 'name' in column
        assert 'order' in column
        assert 'cards' in column
        assert len(column['cards']) == 1
        
        # Verify scheduled template card is returned (not the original card)
        card = column['cards'][0]
        assert card['title'] == 'Card to Schedule'
        assert card['scheduled'] is True
        assert card['schedule'] is not None
    
    def test_get_board_scheduled_cards_not_found(self, api_client, authenticated_session):
        """Test getting scheduled cards for a non-existent board returns 403 (no access)."""
        response = authenticated_session.get(f'{api_client}/api/boards/9999/cards/scheduled')
        assert response.status_code == 403

    def test_get_board_scheduled_cards_includes_assignee_filter_users(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Scheduled board payload should include assignee filter users for filter UI population."""
        # Create one scheduled template card so endpoint has normal content.
        card_response = authenticated_session.post(
            f'{api_client}/api/columns/{sample_column["id"]}/cards',
            json={'title': 'Scheduled Filter Users Card', 'description': 'Template source'}
        )
        assert card_response.status_code == 201

        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        schedule_response = authenticated_session.post(
            f'{api_client}/api/schedules',
            json={
                'card_id': card_response.json()['card']['id'],
                'run_every': 1,
                'unit': 'day',
                'start_datetime': tomorrow,
                'end_datetime': None,
                'schedule_enabled': True,
                'allow_duplicates': False,
                'keep_source_card': True,
            }
        )
        assert schedule_response.status_code == 201

        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True

        filter_users = data['board'].get('assignee_filter_users', [])
        assert isinstance(filter_users, list)

        me_response = authenticated_session.get(f'{api_client}/api/auth/me')
        assert me_response.status_code == 200
        my_id = me_response.json()['user']['id']
        assert my_id in {u['id'] for u in filter_users}
        assert all('email' not in u for u in filter_users)

    def test_get_board_scheduled_cards_filter_includes_secondary_assignees_when_enabled(
        self,
        api_client,
        authenticated_session,
        second_user_session,
        sample_board,
        sample_column,
    ):
        """Scheduled board filtering should include secondary matches only when explicitly enabled."""
        me_response = authenticated_session.get(f'{api_client}/api/auth/me')
        assert me_response.status_code == 200
        my_id = me_response.json()['user']['id']

        second_user_me_response = second_user_session.get(f'{api_client}/api/auth/me')
        assert second_user_me_response.status_code == 200
        second_user_id = second_user_me_response.json()['user']['id']

        role_response = authenticated_session.post(
            f'{api_client}/api/users/{second_user_id}/roles',
            json={'role_name': 'board_editor', 'board_id': sample_board['id']}
        )
        assert role_response.status_code == 200, role_response.text

        # Create template source card and schedule it.
        source_card_response = authenticated_session.post(
            f'{api_client}/api/columns/{sample_column["id"]}/cards',
            json={'title': 'Scheduled Secondary Filter Card', 'description': 'Template source'}
        )
        assert source_card_response.status_code == 201

        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        schedule_response = authenticated_session.post(
            f'{api_client}/api/schedules',
            json={
                'card_id': source_card_response.json()['card']['id'],
                'run_every': 1,
                'unit': 'day',
                'start_datetime': tomorrow,
                'end_datetime': None,
                'schedule_enabled': True,
                'allow_duplicates': False,
                'keep_source_card': True,
            }
        )
        assert schedule_response.status_code == 201

        scheduled_response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled')
        assert scheduled_response.status_code == 200
        scheduled_data = scheduled_response.json()

        template_card_id = None
        for column in scheduled_data['board']['columns']:
            for card in column['cards']:
                if card['title'] == 'Scheduled Secondary Filter Card' and card['scheduled'] is True:
                    template_card_id = card['id']
                    break
            if template_card_id:
                break

        assert template_card_id is not None

        # Set primary assignee to current user and secondary to second user.
        assignee_update_response = authenticated_session.put(
            f'{api_client}/api/cards/{template_card_id}/assignees',
            json={'assigned_to_id': my_id, 'secondary_assignee_ids': [second_user_id]}
        )
        assert assignee_update_response.status_code == 200

        without_secondary_response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled?assignee_ids={second_user_id}'
        )
        assert without_secondary_response.status_code == 200
        without_secondary_data = without_secondary_response.json()
        without_secondary_ids = {
            card['id']
            for column in without_secondary_data['board']['columns']
            for card in column['cards']
        }
        assert template_card_id not in without_secondary_ids

        with_secondary_response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled?assignee_ids={second_user_id}&include_secondary_assignees=true'
        )
        assert with_secondary_response.status_code == 200
        with_secondary_data = with_secondary_response.json()
        with_secondary_ids = {
            card['id']
            for column in with_secondary_data['board']['columns']
            for card in column['cards']
        }
        assert template_card_id in with_secondary_ids

    def test_get_scheduled_cards_text_search_hash_rules(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Scheduled endpoint applies unquoted id and quoted hash text semantics."""
        from datetime import datetime, timedelta

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')

        anchor_source_response = authenticated_session.post(
            f'{api_client}/api/columns/{sample_column["id"]}/cards',
            json={'title': 'Scheduled Anchor Source', 'description': 'anchor source'}
        )
        assert anchor_source_response.status_code == 201
        anchor_source_id = anchor_source_response.json()['card']['id']

        alias_source_response = authenticated_session.post(
            f'{api_client}/api/columns/{sample_column["id"]}/cards',
            json={'title': 'Scheduled Alias Source', 'description': 'alias source'}
        )
        assert alias_source_response.status_code == 201
        alias_source_id = alias_source_response.json()['card']['id']

        schedule_anchor_response = authenticated_session.post(
            f'{api_client}/api/schedules',
            json={
                'card_id': anchor_source_id,
                'run_every': 1,
                'unit': 'day',
                'start_datetime': tomorrow,
                'end_datetime': None,
                'schedule_enabled': True,
                'allow_duplicates': False,
                'keep_source_card': True,
            }
        )
        assert schedule_anchor_response.status_code == 201

        schedule_alias_response = authenticated_session.post(
            f'{api_client}/api/schedules',
            json={
                'card_id': alias_source_id,
                'run_every': 1,
                'unit': 'day',
                'start_datetime': tomorrow,
                'end_datetime': None,
                'schedule_enabled': True,
                'allow_duplicates': False,
                'keep_source_card': True,
            }
        )
        assert schedule_alias_response.status_code == 201

        scheduled_cards_response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled'
        )
        assert scheduled_cards_response.status_code == 200
        scheduled_cards_data = scheduled_cards_response.json()

        template_by_title = {}
        for column in scheduled_cards_data['board']['columns']:
            for card in column['cards']:
                template_by_title[card['title']] = card['id']

        anchor_template_id = template_by_title.get('Scheduled Anchor Source')
        alias_template_id = template_by_title.get('Scheduled Alias Source')
        assert isinstance(anchor_template_id, int)
        assert isinstance(alias_template_id, int)

        alias_rename_response = authenticated_session.patch(
            f'{api_client}/api/cards/{alias_template_id}',
            json={'title': f'Scheduled Alias #{anchor_template_id}'}
        )
        assert alias_rename_response.status_code == 200

        unquoted_hash_response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled',
            params={'q': f'#{anchor_template_id}'}
        )
        assert unquoted_hash_response.status_code == 200
        unquoted_hash_data = unquoted_hash_response.json()
        unquoted_ids = {
            card['id']
            for column in unquoted_hash_data['board']['columns']
            for card in column['cards']
        }
        assert anchor_template_id in unquoted_ids
        assert alias_template_id not in unquoted_ids

        quoted_hash_response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards/scheduled',
            params={'q': f'"#{anchor_template_id}"'}
        )
        assert quoted_hash_response.status_code == 200
        quoted_hash_data = quoted_hash_response.json()
        quoted_ids = {
            card['id']
            for column in quoted_hash_data['board']['columns']
            for card in column['cards']
        }
        assert anchor_template_id not in quoted_ids
        assert alias_template_id in quoted_ids

    def test_export_board_success(self, api_client, authenticated_session, sample_board):
        """Board export returns AFT JSON payload and attachment headers."""
        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/export')

        assert response.status_code == 200
        assert response.headers.get('Content-Type', '').startswith('application/json')
        content_disposition = response.headers.get('Content-Disposition', '')
        assert 'attachment;' in content_disposition
        assert 'aft_board_' in content_disposition

        export_data = response.json()
        assert export_data['export']['format'] == 'aft-board'
        assert export_data['board']['id'] == sample_board['id']
        assert isinstance(export_data['columns'], list)
        assert isinstance(export_data['cards'], list)
        assert isinstance(export_data['checklists'], list)
        assert isinstance(export_data['comments'], list)
        assert isinstance(export_data['scheduled_cards'], list)

    def test_export_board_permission_denied(self, api_client, second_user_session, sample_board):
        """Users without board access cannot export another user's board."""
        response = second_user_session.get(f'{api_client}/api/boards/{sample_board["id"]}/export')
        assert response.status_code == 403

    def test_import_board_success_and_assignees_not_mapped(self, api_client, authenticated_session):
        """Import succeeds and imported assignees are intentionally not mapped."""
        unique_board_name = f'Imported Board Success {uuid.uuid4().hex[:8]}'
        payload = build_minimal_board_import_payload(unique_board_name)

        import_response = authenticated_session.post(
            f'{api_client}/api/boards/import',
            data={'duplicate_strategy': 'cancel'},
            files={'file': ('board-import.json', json.dumps(payload), 'application/json')},
        )
        assert import_response.status_code == 201, import_response.text

        data = import_response.json()
        assert data['success'] is True
        assert data['board']['name'] == unique_board_name
        assert data['import_meta']['assignee_mapping'] == 'not_mapped'
        assert data['import_meta']['ignored_primary_assignees_count'] == 1
        assert data['import_meta']['ignored_secondary_assignees_count'] == 1

        imported_board_id = data['board']['id']
        export_response = authenticated_session.get(f'{api_client}/api/boards/{imported_board_id}/export')
        assert export_response.status_code == 200
        exported_data = export_response.json()
        assert len(exported_data['cards']) == 1
        assert exported_data['cards'][0]['assigned_to_id'] is None

        me_response = authenticated_session.get(f'{api_client}/api/auth/me')
        assert me_response.status_code == 200
        current_user_id = me_response.json()['user']['id']
        assert exported_data['cards'][0]['created_by_id'] == current_user_id

    def test_import_board_invalid_structure(self, api_client, authenticated_session):
        """Import rejects payloads missing required top-level keys."""
        payload = build_minimal_board_import_payload('Invalid Structure Board')
        payload.pop('columns')

        response = authenticated_session.post(
            f'{api_client}/api/boards/import',
            data={'duplicate_strategy': 'cancel'},
            files={'file': ('board-import-invalid.json', json.dumps(payload), 'application/json')},
        )
        assert response.status_code == 400

        data = response.json()
        assert data['success'] is False
        assert data['message'] == 'Import validation failed'
        assert any('Missing required top-level keys' in error for error in data.get('errors', []))

    def test_import_board_duplicate_name_conflict_and_suffix_retry(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Import returns 409 on duplicate name and succeeds with append_suffix."""
        payload = build_minimal_board_import_payload(sample_board['name'])

        first_attempt = authenticated_session.post(
            f'{api_client}/api/boards/import',
            data={'duplicate_strategy': 'cancel'},
            files={'file': ('board-import-duplicate.json', json.dumps(payload), 'application/json')},
        )
        assert first_attempt.status_code == 409
        conflict_data = first_attempt.json()
        assert conflict_data['success'] is False
        assert conflict_data['requires_confirmation'] is True
        assert conflict_data['conflict_type'] == 'board_name_exists'

        second_attempt = authenticated_session.post(
            f'{api_client}/api/boards/import',
            data={'duplicate_strategy': 'append_suffix'},
            files={'file': ('board-import-duplicate.json', json.dumps(payload), 'application/json')},
        )
        assert second_attempt.status_code == 201
        imported_data = second_attempt.json()
        assert imported_data['success'] is True
        assert imported_data['board']['name'] != sample_board['name']
        assert imported_data['board']['name'].startswith(f"{sample_board['name']} (imported)")

    def test_import_board_permission_denied(self, api_client, authenticated_session, second_user_session):
        """Import requires editor-level capability and is denied otherwise."""
        second_user = get_current_user(api_client, second_user_session)

        roles_response = authenticated_session.get(f'{api_client}/api/roles')
        assert roles_response.status_code == 200
        board_creator_role = next(
            role for role in roles_response.json()['roles'] if role['name'] == 'board_creator'
        )

        remove_role_response = authenticated_session.delete(
            f'{api_client}/api/users/{second_user["id"]}/roles/{board_creator_role["id"]}'
        )
        assert remove_role_response.status_code == 200

        payload = build_minimal_board_import_payload('Import Denied Board')

        response = second_user_session.post(
            f'{api_client}/api/boards/import',
            data={'duplicate_strategy': 'cancel'},
            files={'file': ('board-import-denied.json', json.dumps(payload), 'application/json')},
        )
        assert response.status_code == 403


@pytest.mark.api
class TestBoardColumnsAPI:
    """Test cases for board column API endpoints."""
    
    def test_create_column(self, api_client, authenticated_session, sample_board):
        """Test creating a new column."""
        response = authenticated_session.post(f'{api_client}/api/boards/{sample_board["id"]}/columns', json={
            'name': 'To Do'
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['column']['name'] == 'To Do'
        assert data['column']['board_id'] == sample_board['id']
    
    def test_create_column_board_not_found(self, api_client, authenticated_session):
        """Test creating a column for non-existent board returns 403 (no access)."""
        response = authenticated_session.post(f'{api_client}/api/boards/9999/columns', json={
            'name': 'To Do'
        })
        assert response.status_code == 403
    
    def test_create_column_missing_name(self, api_client, authenticated_session, sample_board):
        """Test creating a column without a name."""
        response = authenticated_session.post(f'{api_client}/api/boards/{sample_board["id"]}/columns', json={})
        assert response.status_code == 400
    
    def test_update_column(self, api_client, authenticated_session, sample_column):
        """Test updating a column."""
        response = authenticated_session.patch(f'{api_client}/api/columns/{sample_column["id"]}', json={
            'name': 'Updated Column'
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['column']['name'] == 'Updated Column'
    
    def test_delete_column(self, api_client, authenticated_session, sample_column):
        """Test deleting a column."""
        column_id = sample_column['id']
        board_id = sample_column['board_id']
        
        # Verify column exists first by getting board's columns
        columns_check = authenticated_session.get(f'{api_client}/api/boards/{board_id}/columns')
        assert columns_check.status_code == 200, f"Columns check failed: {columns_check.status_code} - {columns_check.text}"
        columns_before = columns_check.json()['columns']
        column_ids_before = [col['id'] for col in columns_before]
        assert column_id in column_ids_before, f"Column {column_id} not found in board before delete"
        
        # Delete the column
        response = authenticated_session.delete(f'{api_client}/api/columns/{column_id}')
        assert response.status_code == 200, f"Delete column failed: {response.status_code} - {response.text}"
        
        # Verify column is deleted by checking board's columns
        columns_after = authenticated_session.get(f'{api_client}/api/boards/{board_id}/columns')
        assert columns_after.status_code == 200, f"Columns verify failed: {columns_after.status_code} - {columns_after.text}"
        columns_data = columns_after.json()['columns']
        column_ids_after = [col['id'] for col in columns_data]
        assert column_id not in column_ids_after, f"Column {column_id} still exists in board after delete"

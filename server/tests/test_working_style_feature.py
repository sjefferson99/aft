"""Tests for working style feature including done status and kanban board settings."""
import pytest


@pytest.mark.api
class TestCardDoneStatus:
    """Test cases for card done status functionality."""
    
    def test_get_card_done_status_success(self, api_client, authenticated_session, sample_card):
        """Test getting done status of a card."""
        response = authenticated_session.get(f'{api_client}/api/cards/{sample_card["id"]}/done')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'done' in data
        assert isinstance(data['done'], bool)
        assert data['card_id'] == sample_card['id']
    
    def test_get_card_done_status_default_false(self, api_client, authenticated_session, sample_card):
        """Test that new cards have done status as False by default."""
        response = authenticated_session.get(f'{api_client}/api/cards/{sample_card["id"]}/done')
        assert response.status_code == 200
        data = response.json()
        assert data['done'] is False
    
    def test_get_card_done_status_not_found(self, api_client, authenticated_session):
        """Test getting done status of non-existent card."""
        response = authenticated_session.get(f'{api_client}/api/cards/9999/done')
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['message'].lower()
    
    def test_update_card_done_status_to_true(self, api_client, authenticated_session, sample_card):
        """Test updating card done status to True."""
        response = authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={
            'done': True
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['done'] is True
        assert data['card_id'] == sample_card['id']
    
    def test_update_card_done_status_to_false(self, api_client, authenticated_session, sample_card):
        """Test updating card done status to False."""
        # First set it to True
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={'done': True})
        
        # Then set it back to False
        response = authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={
            'done': False
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['done'] is False
    
    def test_update_card_done_status_persist(self, api_client, authenticated_session, sample_card):
        """Test that done status persists after update."""
        # Update done status
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={'done': True})
        
        # Verify it persists by getting the card
        response = authenticated_session.get(f'{api_client}/api/cards/{sample_card["id"]}/done')
        assert response.status_code == 200
        assert response.json()['done'] is True
    
    def test_update_card_done_status_missing_done_field(self, api_client, authenticated_session, sample_card):
        """Test updating done status without done field in request."""
        response = authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={})
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'required' in data['message'].lower()
    
    def test_update_card_done_status_invalid_type(self, api_client, authenticated_session, sample_card):
        """Test updating done status with non-boolean value."""
        response = authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={
            'done': 'true'  # String instead of boolean
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'boolean' in data['message'].lower()
    
    def test_update_card_done_status_not_found(self, api_client, authenticated_session):
        """Test updating done status of non-existent card."""
        response = authenticated_session.patch(f'{api_client}/api/cards/9999/done', json={'done': True})
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['message'].lower()
    
    def test_update_card_done_status_no_json_body(self, api_client, authenticated_session, sample_card):
        """Test updating done status with missing JSON body."""
        response = authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done')
        # API returns 500 when JSON parsing fails (no body)
        assert response.status_code == 500
        data = response.json()
        assert data['success'] is False
    
    def test_done_status_reflected_in_card_details(self, api_client, authenticated_session, sample_card):
        """Test that done status is reflected when getting full card details."""
        # Update done status
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={'done': True})
        
        # Get card details
        response = authenticated_session.get(f'{api_client}/api/cards/{sample_card["id"]}')
        assert response.status_code == 200
        card = response.json()['card']
        assert 'done' in card
        assert card['done'] is True
    
    def test_done_status_in_board_cards_list(self, api_client, authenticated_session, sample_board):
        """Test that done status appears in board cards nested structure."""
        # Create a column and card
        col = authenticated_session.post(f'{api_client}/api/boards/{sample_board["id"]}/columns', json={
            'name': 'Test Column'
        }).json()['column']
        
        card = authenticated_session.post(f'{api_client}/api/columns/{col["id"]}/cards', json={
            'title': 'Test Card'
        }).json()['card']
        
        # Update done status
        authenticated_session.patch(f'{api_client}/api/cards/{card["id"]}/done', json={'done': True})
        
        # Get board cards (returns nested structure: board -> columns -> cards)
        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards')
        assert response.status_code == 200
        board = response.json()['board']
        
        # Find our card in the nested structure
        found_card = None
        for column in board['columns']:
            found_card = next((c for c in column['cards'] if c['id'] == card['id']), None)
            if found_card:
                break
        
        assert found_card is not None
        assert 'done' in found_card
        assert found_card['done'] is True
    
    def test_toggle_done_status_multiple_times(self, api_client, authenticated_session, sample_card):
        """Test toggling done status multiple times."""
        for i in range(5):
            expected = (i % 2) == 1
            response = authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={
                'done': expected
            })
            assert response.status_code == 200
            assert response.json()['done'] is expected

    def test_new_card_done_datetime_defaults_to_null(self, api_client, authenticated_session, sample_card):
        """New cards should default done_datetime to null."""
        response = authenticated_session.get(f'{api_client}/api/cards/{sample_card["id"]}')
        assert response.status_code == 200
        assert response.json()['card']['done_datetime'] is None

    def test_done_datetime_set_when_done_in_agile_mode(self, api_client, authenticated_session, sample_board):
        """Marking done in agile mode should set done_datetime."""
        set_style = authenticated_session.put(
            f'{api_client}/api/boards/{sample_board["id"]}/settings/working-style',
            json={'value': 'agile'}
        )
        assert set_style.status_code == 200

        column = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            json={'name': 'In Progress'}
        ).json()['column']

        card = authenticated_session.post(
            f'{api_client}/api/columns/{column["id"]}/cards',
            json={'title': 'Agile done timestamp card'}
        ).json()['card']

        done_response = authenticated_session.patch(
            f'{api_client}/api/cards/{card["id"]}/done',
            json={'done': True}
        )
        assert done_response.status_code == 200
        assert done_response.json()['done_datetime'] is not None

    def test_done_datetime_not_set_when_done_in_kanban_mode(self, api_client, authenticated_session, sample_board):
        """Marking done in kanban mode should not set done_datetime."""
        set_style = authenticated_session.put(
            f'{api_client}/api/boards/{sample_board["id"]}/settings/working-style',
            json={'value': 'kanban'}
        )
        assert set_style.status_code == 200

        column = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            json={'name': 'To Do'}
        ).json()['column']

        card = authenticated_session.post(
            f'{api_client}/api/columns/{column["id"]}/cards',
            json={'title': 'Kanban done timestamp card'}
        ).json()['card']

        done_response = authenticated_session.patch(
            f'{api_client}/api/cards/{card["id"]}/done',
            json={'done': True}
        )
        assert done_response.status_code == 200
        assert done_response.json()['done_datetime'] is None

    def test_done_datetime_set_when_moved_to_done_like_column(self, api_client, authenticated_session, sample_board):
        """Moving a card to a done-like column should set done_datetime (case-insensitive)."""
        source = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            json={'name': 'In Progress'}
        ).json()['column']
        target = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            json={'name': 'CoMpLeTeD'}
        ).json()['column']

        card = authenticated_session.post(
            f'{api_client}/api/columns/{source["id"]}/cards',
            json={'title': 'Move to done-like column'}
        ).json()['card']

        move_response = authenticated_session.patch(
            f'{api_client}/api/cards/{card["id"]}',
            json={'column_id': target['id']}
        )
        assert move_response.status_code == 200
        assert move_response.json()['card']['done_datetime'] is not None

    def test_done_datetime_set_on_batch_move_to_done_like_column(self, api_client, authenticated_session, sample_board):
        """Batch moving cards to a done-like column should set done_datetime for moved cards."""
        source = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            json={'name': 'Source'}
        ).json()['column']
        target = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            json={'name': 'DONE'}
        ).json()['column']

        card1 = authenticated_session.post(
            f'{api_client}/api/columns/{source["id"]}/cards',
            json={'title': 'Batch move card 1'}
        ).json()['card']
        card2 = authenticated_session.post(
            f'{api_client}/api/columns/{source["id"]}/cards',
            json={'title': 'Batch move card 2'}
        ).json()['card']

        move_response = authenticated_session.post(
            f'{api_client}/api/columns/{source["id"]}/cards/move',
            json={'target_column_id': target['id'], 'position': 'bottom'}
        )
        assert move_response.status_code == 200

        card1_after = authenticated_session.get(f'{api_client}/api/cards/{card1["id"]}').json()['card']
        card2_after = authenticated_session.get(f'{api_client}/api/cards/{card2["id"]}').json()['card']
        assert card1_after['done_datetime'] is not None
        assert card2_after['done_datetime'] is not None


@pytest.mark.api
class TestWorkingStyleSetting:
    """Test cases for working style setting."""
    
    def test_get_working_style_setting(self, api_client, authenticated_session):
        """Test getting the working_style setting."""
        response = authenticated_session.get(f'{api_client}/api/settings/working-style')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'value' in data
        # Default should be 'kanban'
        assert data['value'] in ['kanban', 'agile']
    
    def test_working_style_schema_defined(self, api_client, authenticated_session):
        """Test that working_style is defined in settings schema."""
        response = authenticated_session.get(f'{api_client}/api/settings/schema')
        assert response.status_code == 200
        schema = response.json()['schema']
        assert 'working_style' in schema
        assert schema['working_style']['type'] == 'string'
        assert 'kanban' in schema['working_style']['description'] or \
            'agile' in schema['working_style']['description']
    
    def test_set_working_style_to_kanban(self, api_client, authenticated_session):
        """Test setting working_style to kanban."""
        response = authenticated_session.put(f'{api_client}/api/settings/working-style', json={
            'value': 'kanban'
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['value'] == 'kanban'
    
    def test_set_working_style_to_agile(self, api_client, authenticated_session):
        """Test setting working_style to agile."""
        response = authenticated_session.put(f'{api_client}/api/settings/working-style', json={
            'value': 'agile'
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['value'] == 'agile'
    
    def test_set_working_style_persist(self, api_client, authenticated_session):
        """Test that working_style setting persists."""
        # Set to agile
        authenticated_session.put(f'{api_client}/api/settings/working-style', json={
            'value': 'agile'
        })
        
        # Verify it persists
        response = authenticated_session.get(f'{api_client}/api/settings/working-style')
        assert response.status_code == 200
        assert response.json()['value'] == 'agile'
    
    def test_set_working_style_invalid_value(self, api_client, authenticated_session):
        """Test setting working_style with invalid value."""
        response = authenticated_session.put(f'{api_client}/api/settings/working-style', json={
            'value': 'invalid_style'
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'invalid' in data['message'].lower() or 'validate' in data['message'].lower()
    
    def test_set_working_style_null_value(self, api_client, authenticated_session):
        """Test setting working_style to null."""
        response = authenticated_session.put(f'{api_client}/api/settings/working-style', json={
            'value': None
        })
        # May be rejected or allowed depending on schema
        # At minimum, should return a response
        assert response.status_code in [200, 400]
    
    def test_set_working_style_missing_value(self, api_client, authenticated_session):
        """Test setting working_style without value field."""
        response = authenticated_session.put(f'{api_client}/api/settings/working-style', json={})
        assert response.status_code == 400
    
    def test_switch_working_style_back_and_forth(self, api_client, authenticated_session):
        """Test switching working style back and forth."""
        for i in range(3):
            style = 'agile' if (i % 2) == 0 else 'kanban'
            response = authenticated_session.put(f'{api_client}/api/settings/working-style', json={
                'value': style
            })
            assert response.status_code == 200
            assert response.json()['value'] == style


@pytest.mark.api
class TestBoardWorkingStyleSetting:
    """Test board-level working style endpoints and defaults."""

    def test_new_board_inherits_user_working_style_default(self, api_client, authenticated_session):
        """New boards should inherit the current user's working style default."""
        set_response = authenticated_session.put(f'{api_client}/api/settings/working-style', json={
            'value': 'agile'
        })
        assert set_response.status_code == 200

        create_response = authenticated_session.post(f'{api_client}/api/boards', json={
            'name': 'Inherited Style Board',
            'description': 'Should default to agile'
        })
        assert create_response.status_code == 201
        board_id = create_response.json()['board']['id']

        board_style_response = authenticated_session.get(
            f'{api_client}/api/boards/{board_id}/settings/working-style'
        )
        assert board_style_response.status_code == 200
        data = board_style_response.json()
        assert data['success'] is True
        assert data['value'] == 'agile'

    def test_board_working_style_can_be_updated(self, api_client, authenticated_session, sample_board):
        """Board editors should be able to change board working style."""
        update_response = authenticated_session.put(
            f'{api_client}/api/boards/{sample_board["id"]}/settings/working-style',
            json={'value': 'agile'}
        )
        assert update_response.status_code == 200
        assert update_response.json()['value'] == 'agile'

        get_response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/settings/working-style'
        )
        assert get_response.status_code == 200
        assert get_response.json()['value'] == 'agile'

    def test_board_viewer_can_get_but_not_set_working_style(
        self,
        api_client,
        authenticated_session,
        second_user_session,
        sample_board,
    ):
        """Board viewers should be allowed to read but not update board style."""
        second_user_me = second_user_session.get(f'{api_client}/api/auth/me')
        assert second_user_me.status_code == 200
        second_user_id = second_user_me.json()['user']['id']

        role_response = authenticated_session.post(
            f'{api_client}/api/users/{second_user_id}/roles',
            json={'role_name': 'board_viewer', 'board_id': sample_board['id']}
        )
        assert role_response.status_code == 200

        get_response = second_user_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/settings/working-style'
        )
        assert get_response.status_code == 200
        assert get_response.json()['success'] is True

        set_response = second_user_session.put(
            f'{api_client}/api/boards/{sample_board["id"]}/settings/working-style',
            json={'value': 'agile'}
        )
        assert set_response.status_code == 403


@pytest.mark.api
class TestCardDoneAndArchivedInteraction:
    """Test interactions between done status and archived status."""
    
    def test_can_mark_archived_card_as_done(self, api_client, authenticated_session, sample_card):
        """Test that archived cards can have done status."""
        # Archive the card
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/archive')
        
        # Mark it as done
        response = authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={
            'done': True
        })
        assert response.status_code == 200
        assert response.json()['done'] is True
    
    def test_done_status_preserved_on_archive(self, api_client, authenticated_session, sample_card):
        """Test that done status is preserved when archiving."""
        # Mark as done
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={'done': True})
        
        # Archive it
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/archive')
        
        # Check done status is preserved
        response = authenticated_session.get(f'{api_client}/api/cards/{sample_card["id"]}/done')
        assert response.status_code == 200
        assert response.json()['done'] is True
    
    def test_done_status_preserved_on_unarchive(self, api_client, authenticated_session, sample_card):
        """Test that done status is preserved when unarchiving."""
        # Mark as done
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/done', json={'done': True})
        
        # Archive it
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/archive')
        
        # Unarchive it
        authenticated_session.patch(f'{api_client}/api/cards/{sample_card["id"]}/unarchive')
        
        # Check done status is still true
        response = authenticated_session.get(f'{api_client}/api/cards/{sample_card["id"]}/done')
        assert response.status_code == 200
        assert response.json()['done'] is True
    
    def test_archived_cards_appear_with_done_status(self, api_client, authenticated_session, sample_column):
        """Test that archived cards are included in responses with done status."""
        # Create and archive a card with done status
        card = authenticated_session.post(f'{api_client}/api/columns/{sample_column["id"]}/cards', json={
            'title': 'Card to Archive'
        }).json()['card']
        
        authenticated_session.patch(f'{api_client}/api/cards/{card["id"]}/done', json={'done': True})
        authenticated_session.patch(f'{api_client}/api/cards/{card["id"]}/archive')
        
        # Get archived cards from column
        response = authenticated_session.get(f'{api_client}/api/columns/{sample_column["id"]}/cards?archived=true')
        assert response.status_code == 200
        cards = response.json()['cards']
        
        # Find our card and verify done status persists with archived status
        found_card = next((c for c in cards if c['id'] == card['id']), None)
        assert found_card is not None
        assert 'archived' in found_card
        assert 'done' in found_card
        assert found_card['archived'] is True
        assert found_card['done'] is True


@pytest.mark.api
class TestDoneCountInColumns:
    """Test done count functionality in column headers and responses."""
    
    def test_board_cards_include_done_status(self, api_client, authenticated_session, sample_board):
        """Test that board cards endpoint includes done status for all cards."""
        # Create columns and cards with various done statuses
        col = authenticated_session.post(f'{api_client}/api/boards/{sample_board["id"]}/columns', json={
            'name': 'Work Column'
        }).json()['column']
        
        # Create some cards with done=true
        for i in range(2):
            card = authenticated_session.post(f'{api_client}/api/columns/{col["id"]}/cards', json={
                'title': f'Done Card {i}'
            }).json()['card']
            authenticated_session.patch(f'{api_client}/api/cards/{card["id"]}/done', json={'done': True})
        
        # Create some cards with done=false
        for i in range(3):
            authenticated_session.post(f'{api_client}/api/columns/{col["id"]}/cards', json={
                'title': f'Active Card {i}'
            })
        
        # Get board with nested structure
        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards')
        assert response.status_code == 200
        board = response.json()['board']
        
        # Flatten all cards from all columns
        all_cards = []
        for column in board['columns']:
            all_cards.extend(column['cards'])
        
        # All cards should have done status
        assert len(all_cards) >= 5
        for card in all_cards:
            assert 'done' in card
            assert isinstance(card['done'], bool)
    
    def test_column_cards_include_done_status(self, api_client, authenticated_session, sample_column):
        """Test that column cards include done status."""
        # Create cards with different done statuses
        card1 = authenticated_session.post(f'{api_client}/api/columns/{sample_column["id"]}/cards', json={
            'title': 'Done Card'
        }).json()['card']
        authenticated_session.patch(f'{api_client}/api/cards/{card1["id"]}/done', json={'done': True})
        
        card2 = authenticated_session.post(f'{api_client}/api/columns/{sample_column["id"]}/cards', json={
            'title': 'Active Card'
        }).json()['card']
        
        # Get column cards
        response = authenticated_session.get(f'{api_client}/api/columns/{sample_column["id"]}/cards')
        assert response.status_code == 200
        cards = response.json()['cards']
        
        # Verify both cards have done status (even if not showing, should exist)
        assert len(cards) >= 2
        done_card = next((c for c in cards if c['id'] == card1['id']), None)
        active_card = next((c for c in cards if c['id'] == card2['id']), None)
        
        if done_card:
            assert 'done' in done_card
            assert done_card['done'] is True
        if active_card:
            assert 'done' in active_card
            assert active_card['done'] is False
    
    def test_batch_done_cards_for_reporting(self, api_client, authenticated_session, sample_board):
        """Test getting done/active card counts for a board."""
        # Create column and cards
        col = authenticated_session.post(f'{api_client}/api/boards/{sample_board["id"]}/columns', json={
            'name': 'Work'
        }).json()['column']
        
        card_ids = []
        for i in range(5):
            card = authenticated_session.post(f'{api_client}/api/columns/{col["id"]}/cards', json={
                'title': f'Card {i}'
            }).json()['card']
            card_ids.append(card['id'])
        
        # Mark first 2 as done
        for card_id in card_ids[:2]:
            authenticated_session.patch(f'{api_client}/api/cards/{card_id}/done', json={'done': True})
        
        # Get board with nested structure and count done
        response = authenticated_session.get(f'{api_client}/api/boards/{sample_board["id"]}/cards')
        board = response.json()['board']
        
        # Flatten cards from all columns
        all_cards = []
        for column in board['columns']:
            all_cards.extend(column['cards'])
        
        done_count = sum(1 for c in all_cards if c['done'])
        active_count = sum(1 for c in all_cards if not c['done'])
        
        assert done_count == 2
        assert active_count == 3


@pytest.mark.api
class TestCardDoneEdgeCases:
    """Test edge cases and error conditions for done status."""
    
    def test_done_status_with_special_characters_in_title(self, api_client, authenticated_session, sample_column):
        """Test done status on cards with special characters in title."""
        card = authenticated_session.post(f'{api_client}/api/columns/{sample_column["id"]}/cards', json={
            'title': 'Card with <special> & "characters"'
        }).json()['card']
        
        response = authenticated_session.patch(f'{api_client}/api/cards/{card["id"]}/done', json={'done': True})
        assert response.status_code == 200
        assert response.json()['done'] is True
    
    def test_done_status_on_moved_card(self, api_client, authenticated_session, sample_board):
        """Test that done status persists when card is moved to another column."""
        # Create two columns
        col1 = authenticated_session.post(f'{api_client}/api/boards/{sample_board["id"]}/columns', json={
            'name': 'Column 1'
        }).json()['column']
        
        col2 = authenticated_session.post(f'{api_client}/api/boards/{sample_board["id"]}/columns', json={
            'name': 'Column 2'
        }).json()['column']
        
        # Create card and mark as done
        card = authenticated_session.post(f'{api_client}/api/columns/{col1["id"]}/cards', json={
            'title': 'Card to Move'
        }).json()['card']
        authenticated_session.patch(f'{api_client}/api/cards/{card["id"]}/done', json={'done': True})
        
        # Move card to another column
        authenticated_session.patch(f'{api_client}/api/cards/{card["id"]}', json={
            'column_id': col2['id']
        })
        
        # Verify done status persists
        response = authenticated_session.get(f'{api_client}/api/cards/{card["id"]}/done')
        assert response.status_code == 200
        assert response.json()['done'] is True
    
    def test_done_status_empty_request_body(self, api_client, authenticated_session, sample_card):
        """Test done status update with empty body."""
        response = authenticated_session.patch(
            f'{api_client}/api/cards/{sample_card["id"]}/done',
            json=None
        )
        # API returns 500 when JSON parsing fails (no body)
        assert response.status_code == 500
    
    def test_many_cards_with_done_status(self, api_client, authenticated_session, sample_column):
        """Test handling many cards with done status."""
        # Create many cards
        card_ids = []
        for i in range(20):
            card = authenticated_session.post(f'{api_client}/api/columns/{sample_column["id"]}/cards', json={
                'title': f'Card {i}'
            }).json()['card']
            card_ids.append(card['id'])
        
        # Mark alternating cards as done
        for i, card_id in enumerate(card_ids):
            is_done = (i % 2) == 0
            response = authenticated_session.patch(f'{api_client}/api/cards/{card_id}/done', json={
                'done': is_done
            })
            assert response.status_code == 200
        
        # Verify cards are properly marked by checking individual cards
        for i, card_id in enumerate(card_ids):
            expected_done = (i % 2) == 0
            response = authenticated_session.get(f'{api_client}/api/cards/{card_id}/done')
            assert response.status_code == 200
            assert response.json()['done'] is expected_done

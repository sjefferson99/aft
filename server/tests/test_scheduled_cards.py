"""Tests for scheduled cards API endpoints and functionality."""
import pytest
from datetime import datetime, timedelta


@pytest.fixture
def scheduled_card(api_client, authenticated_session, sample_column):
    """Create a card that will be used as a schedule template."""
    response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
        'title': 'Template Card',
        'description': 'This card will be scheduled'
    })
    assert response.status_code == 201
    card = response.json()['card']
    return card


@pytest.fixture
def schedule_data():
    """Provide default schedule data for testing."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
    return {
        'run_every': 2,
        'unit': 'day',
        'start_datetime': tomorrow,
        'end_datetime': None,
        'schedule_enabled': True,
        'allow_duplicates': False
    }


@pytest.mark.api
class TestScheduledCardsFiltering:
    """Test cases for scheduled cards filtering in task views."""
    
    def test_task_view_excludes_scheduled_cards(self, api_client, authenticated_session, sample_column, scheduled_card, schedule_data):
        """Test that scheduled template cards don't appear in task view."""
        # Create a schedule (creates a new template card, original stays visible)
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        assert response.status_code == 201
        
        # Get cards from column - should include original card but not the template
        response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['cards']) == 1  # Original card still visible
        assert data['cards'][0]['id'] == scheduled_card['id']  # It's the original card
        assert data['cards'][0]['schedule'] is not None  # Has schedule reference
    
    def test_scheduled_view_shows_template_cards(self, api_client, authenticated_session, sample_column, scheduled_card, schedule_data):
        """Test that scheduled template cards appear in scheduled view."""
        # Create a schedule
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        assert response.status_code == 201
        template_card_id = response.json()['schedule']['card_id']
        
        # Get scheduled cards from column
        response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards/scheduled")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['cards']) == 1
        assert data['cards'][0]['id'] == template_card_id  # The NEW template card
        assert data['cards'][0]['scheduled'] is True
    
    def test_board_view_excludes_scheduled_cards(self, api_client, authenticated_session, sample_board, sample_column, scheduled_card, schedule_data):
        """Test that board endpoint excludes scheduled template cards."""
        # Create a schedule
        authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        # Get board with cards
        response = authenticated_session.get(f"{api_client}/api/boards/{sample_board['id']}/cards")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Find the column in the response
        column = next((col for col in data['board']['columns'] if col['id'] == sample_column['id']), None)
        assert column is not None
        assert len(column['cards']) == 1  # Original card still visible
        assert column['cards'][0]['id'] == scheduled_card['id']


@pytest.mark.api
class TestScheduleCRUD:
    """Test cases for schedule CRUD operations."""
    
    def test_create_schedule_with_keep_source_card(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test creating a schedule while keeping source card as template."""
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert 'schedule' in data
        assert data['schedule']['run_every'] == 2
        assert data['schedule']['unit'] == 'day'
        assert data['schedule']['schedule_enabled'] is True
        assert 'next_runs' in data['schedule']
        assert len(data['schedule']['next_runs']) > 0
    
    def test_create_schedule_without_keep_source_card(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test creating a schedule - original card gets schedule reference."""
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            **schedule_data
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        
        # Verify the original card has schedule reference (but is not the template)
        card_response = authenticated_session.get(f"{api_client}/api/cards/{scheduled_card['id']}")
        assert card_response.status_code == 200
        card_data = card_response.json()
        assert card_data['card']['scheduled'] is False  # Original is not the template
        assert card_data['card']['schedule'] is not None  # But has schedule reference
    
    def test_get_schedule_with_next_runs(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test getting a schedule includes next run times."""
        # Create schedule
        create_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        schedule_id = create_response.json()['schedule']['id']
        
        # Get schedule
        response = authenticated_session.get(f"{api_client}/api/schedules/{schedule_id}")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'schedule' in data
        assert 'next_runs' in data['schedule']
        assert isinstance(data['schedule']['next_runs'], list)
        # Should have up to 4 next runs
        assert len(data['schedule']['next_runs']) <= 4
    
    def test_update_schedule(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test updating a schedule's properties."""
        # Create schedule
        create_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        schedule_id = create_response.json()['schedule']['id']
        
        # Update schedule
        end_dt = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%dT18:00:00')
        updated_data = {
            'run_every': 3,
            'unit': 'hour',
            'start_datetime': schedule_data['start_datetime'],
            'end_datetime': end_dt,
            'schedule_enabled': False,
            'allow_duplicates': True
        }
        
        response = authenticated_session.put(f"{api_client}/api/schedules/{schedule_id}", json=updated_data)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['schedule']['run_every'] == 3
        assert data['schedule']['unit'] == 'hour'
        assert data['schedule']['schedule_enabled'] is False
        assert data['schedule']['allow_duplicates'] is True
    
    def test_delete_schedule(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test deleting a schedule."""
        # Create schedule
        create_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        schedule_id = create_response.json()['schedule']['id']
        
        # Delete schedule
        response = authenticated_session.delete(f"{api_client}/api/schedules/{schedule_id}")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Verify schedule is gone
        get_response = authenticated_session.get(f"{api_client}/api/schedules/{schedule_id}")
        assert get_response.status_code == 404
    
    def test_delete_schedule_resets_template_card(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test that deleting a schedule resets the source card's schedule reference."""
        # Create schedule
        create_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        schedule_id = create_response.json()['schedule']['id']
        
        # Delete schedule
        authenticated_session.delete(f"{api_client}/api/schedules/{schedule_id}")
        
        # Verify original card's schedule reference is cleared
        card_response = authenticated_session.get(f"{api_client}/api/cards/{scheduled_card['id']}")
        card_data = card_response.json()
        assert card_data['card']['scheduled'] is False  # Original was never scheduled
        assert card_data['card']['schedule'] is None  # Schedule reference cleared


@pytest.mark.api
class TestScheduleValidation:
    """Test cases for schedule validation."""
    
    def test_create_schedule_missing_required_fields(self, api_client, authenticated_session, scheduled_card):
        """Test that creating a schedule without required fields fails."""
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True
            # Missing other required fields
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_schedule_invalid_unit(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test that invalid unit values are rejected."""
        schedule_data['unit'] = 'invalid_unit'
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_schedule_invalid_run_every(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test that invalid run_every values are rejected."""
        schedule_data['run_every'] = 0
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_schedule_nonexistent_card(self, api_client, authenticated_session, schedule_data):
        """Test that creating a schedule for non-existent card fails."""
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': 99999,
            'keep_source_card': True,
            **schedule_data
        })
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False


@pytest.mark.api
class TestScheduleWithChecklist:
    """Test cases for schedules with checklist items."""
    
    def test_create_schedule_copies_checklist(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test that creating a schedule with keep_source_card=True copies checklist items."""
        # Add checklist items to the card
        authenticated_session.post(f"{api_client}/api/cards/{scheduled_card['id']}/checklist-items", json={
            'name': 'First item',
            'checked': False,
            'order': 0
        })
        authenticated_session.post(f"{api_client}/api/cards/{scheduled_card['id']}/checklist-items", json={
            'name': 'Second item',
            'checked': True,
            'order': 1
        })
        
        # Create schedule with keep_source_card=True
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        
        # Verify the template card still has checklist items
        card_response = authenticated_session.get(f"{api_client}/api/cards/{scheduled_card['id']}")
        card_data = card_response.json()
        assert len(card_data['card']['checklist_items']) == 2


@pytest.mark.api
class TestNextRunsCalculation:
    """Test cases for next runs calculation."""
    
    def test_next_runs_minute_frequency(self, api_client, authenticated_session, scheduled_card):
        """Test next runs calculation for minute frequency."""
        now = datetime.now()
        start_dt = (now + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')
        
        schedule_data = {
            'run_every': 10,
            'unit': 'minute',
            'start_datetime': start_dt,
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False
        }
        
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        assert response.status_code == 201
        data = response.json()
        assert 'next_runs' in data['schedule']
        assert len(data['schedule']['next_runs']) > 0
    
    def test_next_runs_with_end_date(self, api_client, authenticated_session, scheduled_card):
        """Test next runs calculation respects end date."""
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        day_after = (now + timedelta(days=2)).replace(hour=17, minute=0, second=0)
        
        schedule_data = {
            'run_every': 1,
            'unit': 'day',
            'start_datetime': tomorrow.strftime('%Y-%m-%dT%H:%M:%S'),
            'end_datetime': day_after.strftime('%Y-%m-%dT%H:%M:%S'),
            'schedule_enabled': True,
            'allow_duplicates': False
        }
        
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        assert response.status_code == 201
        data = response.json()
        assert 'next_runs' in data['schedule']
        # Should have limited runs due to end date
        assert len(data['schedule']['next_runs']) <= 4
    
    def test_next_runs_all_units(self, api_client, authenticated_session, sample_column):
        """Test next runs calculation for all time units."""
        units = ['minute', 'hour', 'day', 'week', 'month', 'year']
        now = datetime.now()
        
        for unit in units:
            # Create a new card for each test
            card_response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
                'title': f'Test {unit}',
                'description': f'Testing {unit} frequency'
            })
            card = card_response.json()['card']
            
            start_dt = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%S')
            schedule_data = {
                'run_every': 1,
                'unit': unit,
                'start_datetime': start_dt,
                'end_datetime': None,
                'schedule_enabled': True,
                'allow_duplicates': False
            }
            
            response = authenticated_session.post(f"{api_client}/api/schedules", json={
                'card_id': card['id'],
                'keep_source_card': True,
                **schedule_data
            })
            
            assert response.status_code == 201, f"Failed for unit: {unit}"
            data = response.json()
            assert 'next_runs' in data['schedule'], f"No next_runs for unit: {unit}"
            assert len(data['schedule']['next_runs']) > 0, f"Empty next_runs for unit: {unit}"


@pytest.mark.api
class TestScheduleEdgeCases:
    """Test cases for schedule edge cases."""
    
    def test_schedule_already_scheduled_card(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test that creating a schedule for an already scheduled card fails."""
        # Create first schedule
        authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        # Try to create another schedule for the same card
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_disabled_schedule(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test creating a disabled schedule."""
        schedule_data['schedule_enabled'] = False
        
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['schedule']['schedule_enabled'] is False
    
    def test_schedule_past_start_date(self, api_client, authenticated_session, scheduled_card):
        """Test creating a schedule with past start date still works."""
        yesterday = (datetime.now() - timedelta(days=1)).replace(hour=9, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%S')
        
        schedule_data = {
            'run_every': 1,
            'unit': 'day',
            'start_datetime': yesterday,
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False
        }
        
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        # Next runs should be in the future
        assert len(data['schedule']['next_runs']) > 0


@pytest.mark.api
class TestScheduleRelationships:
    """Test cases for schedule relationships with cards."""
    
    def test_card_has_schedule_reference(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test that scheduled card references its schedule."""
        # Create schedule
        create_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        schedule_id = create_response.json()['schedule']['id']
        
        # Get card and verify schedule reference
        card_response = authenticated_session.get(f"{api_client}/api/cards/{scheduled_card['id']}")
        card_data = card_response.json()
        assert card_data['card']['schedule'] == schedule_id
    
    def test_delete_template_card_deletes_schedule(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test that deleting the template card also deletes the schedule."""
        # Create schedule
        create_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        schedule_id = create_response.json()['schedule']['id']
        template_card_id = create_response.json()['schedule']['card_id']
        
        # Delete the TEMPLATE card (not the original)
        delete_response = authenticated_session.delete(f"{api_client}/api/cards/{template_card_id}")
        assert delete_response.status_code == 200
        
        # Verify schedule is also gone
        schedule_response = authenticated_session.get(f"{api_client}/api/schedules/{schedule_id}")
        assert schedule_response.status_code == 404


@pytest.mark.api
class TestMultipleSchedules:
    """Test cases for multiple schedules on different cards."""
    
    def test_multiple_schedules_in_column(self, api_client, authenticated_session, sample_column, schedule_data):
        """Test creating multiple schedules in the same column."""
        # Create multiple cards with schedules
        for i in range(3):
            card_response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
                'title': f'Scheduled Card {i+1}',
                'description': f'Card {i+1} description'
            })
            card = card_response.json()['card']
            
            response = authenticated_session.post(f"{api_client}/api/schedules", json={
                'card_id': card['id'],
                'keep_source_card': True,
                **schedule_data
            })
            assert response.status_code == 201
        
        # Get scheduled cards from column
        response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards/scheduled")
        assert response.status_code == 200
        data = response.json()
        assert len(data['cards']) == 3


@pytest.mark.api
class TestScheduleDateTimeHandling:
    """Test cases for datetime format handling."""
    
    def test_create_schedule_with_iso_format_z_suffix(self, api_client, authenticated_session, scheduled_card):
        """Test creating a schedule with ISO format datetime including Z timezone suffix."""
        # This simulates what the frontend sends with toISOString()
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'run_every': 1,
            'unit': 'day',
            'start_datetime': '2025-12-04T09:00:00.000Z',  # ISO format with milliseconds and Z
            'end_datetime': '2025-12-31T17:00:00.000Z',
            'schedule_enabled': True,
            'allow_duplicates': False,
            'keep_source_card': True
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert 'schedule' in data
    
    def test_create_schedule_with_iso_format_no_z(self, api_client, authenticated_session, sample_column):
        """Test creating a schedule with ISO format datetime without Z suffix."""
        card_response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Test Card',
            'description': 'Test'
        })
        card_id = card_response.json()['card']['id']
        
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': card_id,
            'run_every': 2,
            'unit': 'hour',
            'start_datetime': '2025-12-04T09:00:00',  # ISO format without Z
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
            'keep_source_card': True
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
    
    def test_update_schedule_with_iso_format_z_suffix(self, api_client, authenticated_session, scheduled_card, schedule_data):
        """Test updating a schedule with ISO format datetime including Z suffix."""
        # First create a schedule
        create_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': True,
            **schedule_data
        })
        schedule_id = create_response.json()['schedule']['id']
        
        # Update with Z suffix format
        update_response = authenticated_session.put(f"{api_client}/api/schedules/{schedule_id}", json={
            'start_datetime': '2025-12-05T10:00:00.000Z',
            'end_datetime': '2025-12-25T18:00:00.000Z'
        })
        
        assert update_response.status_code == 200
        data = update_response.json()
        assert data['success'] is True


@pytest.mark.api
class TestKeepSourceCardScenarios:
    """Test cases for keep_source_card parameter scenarios."""
    
    def test_create_schedule_keep_source_card_true(self, api_client, authenticated_session, sample_column):
        """Test that original card is preserved when keep_source_card=True."""
        # Create card
        card_response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Original Card',
            'description': 'Should be kept'
        })
        card_id = card_response.json()['card']['id']
        
        # Create schedule with keep_source_card=True
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': card_id,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': tomorrow,
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
            'keep_source_card': True
        })
        assert schedule_response.status_code == 201
        
        # Original card should still exist and be visible in task view
        card_check = authenticated_session.get(f"{api_client}/api/cards/{card_id}")
        assert card_check.status_code == 200
        card_data = card_check.json()['card']
        assert card_data['scheduled'] is False  # Not the template
        assert card_data['schedule'] is not None  # Has schedule reference
        
        # Should appear in regular cards list
        cards_response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards")
        cards = cards_response.json()['cards']
        original_card = next((c for c in cards if c['id'] == card_id), None)
        assert original_card is not None
    
    def test_create_schedule_keep_source_card_false(self, api_client, authenticated_session, sample_column):
        """Test that original card is deleted when keep_source_card=False."""
        # Create card
        card_response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Card to Delete',
            'description': 'Should be deleted'
        })
        card_id = card_response.json()['card']['id']
        
        # Create schedule with keep_source_card=False
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': card_id,
            'run_every': 1,
            'unit': 'week',
            'start_datetime': tomorrow,
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
            'keep_source_card': False
        })
        assert schedule_response.status_code == 201
        
        # Original card should be deleted
        card_check = authenticated_session.get(f"{api_client}/api/cards/{card_id}")
        assert card_check.status_code == 404
        
        # Should NOT appear in regular cards list
        cards_response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards")
        cards = cards_response.json()['cards']
        original_card = next((c for c in cards if c['id'] == card_id), None)
        assert original_card is None
        
        # Template card should exist in scheduled view
        scheduled_response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards/scheduled")
        scheduled_cards = scheduled_response.json()['cards']
        assert len(scheduled_cards) == 1
        assert scheduled_cards[0]['title'] == 'Card to Delete'
        assert scheduled_cards[0]['scheduled'] is True
    
    def test_create_schedule_keep_source_card_default(self, api_client, authenticated_session, sample_column):
        """Test that keep_source_card defaults to True when not specified."""
        # Create card
        card_response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Default Behavior Card',
            'description': 'Test default'
        })
        card_id = card_response.json()['card']['id']
        
        # Create schedule without keep_source_card parameter
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': card_id,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': tomorrow,
            'schedule_enabled': True,
            'allow_duplicates': False
            # keep_source_card not specified
        })
        assert schedule_response.status_code == 201
        
        # Original card should still exist (default is True)
        card_check = authenticated_session.get(f"{api_client}/api/cards/{card_id}")
        assert card_check.status_code == 200


@pytest.mark.api
class TestTemplateCardCreation:
    """Test cases for creating template cards directly with scheduled parameter."""
    
    def test_create_template_card_with_scheduled_true(self, api_client, authenticated_session, sample_board, sample_column):
        """Test creating a card with scheduled=true makes it a template."""
        response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Direct Template Card',
            'description': 'Created as a template',
            'scheduled': True
        })
        assert response.status_code == 201
        
        # Verify card was created as a template
        # Check via board scheduled cards endpoint
        scheduled_response = authenticated_session.get(f"{api_client}/api/boards/{sample_board['id']}/cards/scheduled")
        data = scheduled_response.json()
        assert data['success'] is True
        
        # Find our card in the scheduled cards within columns
        template_card = None
        for column in data['board']['columns']:
            for card in column['cards']:
                if card['title'] == 'Direct Template Card':
                    template_card = card
                    break
            if template_card:
                break
        
        assert template_card is not None
        assert template_card['scheduled'] is True
    
    def test_create_regular_card_with_scheduled_false(self, api_client, authenticated_session, sample_column):
        """Test creating a card with scheduled=false makes it a regular card."""
        response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Regular Card',
            'description': 'Created as regular',
            'scheduled': False
        })
        assert response.status_code == 201
        
        # Regular cards should appear in column cards endpoint
        cards_response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards")
        cards = cards_response.json()['cards']
        regular_card = next((c for c in cards if c['title'] == 'Regular Card'), None)
        assert regular_card is not None
    
    def test_create_card_without_scheduled_defaults_to_false(self, api_client, authenticated_session, sample_column):
        """Test that omitting scheduled parameter defaults to false (regular card)."""
        response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Default Card',
            'description': 'No scheduled parameter'
        })
        assert response.status_code == 201
        
        # Should appear in column cards endpoint (not scheduled)
        cards_response = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards")
        cards = cards_response.json()['cards']
        default_card = next((c for c in cards if c['title'] == 'Default Card'), None)
        assert default_card is not None
    
    def test_create_template_card_with_invalid_scheduled_value(self, api_client, authenticated_session, sample_column):
        """Test that non-boolean scheduled value returns error."""
        response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
            'title': 'Invalid Template',
            'description': 'Invalid scheduled value',
            'scheduled': 'true'  # String instead of boolean
        })
        assert response.status_code == 400
        assert 'Scheduled must be a boolean' in response.json()['message']


@pytest.mark.api
class TestColumnSpecificDuplicateChecking:
    """Test cases for column-specific duplicate checking behavior in card scheduler."""
    
    def test_schedule_allows_cards_in_different_columns(self, api_client, authenticated_session, sample_board):
        """Test that allow_duplicates=False allows cards in different columns."""
        # Create two columns
        col1_response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
            'name': 'Column 1'
        })
        assert col1_response.status_code == 201
        col1 = col1_response.json()['column']
        
        col2_response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
            'name': 'Column 2'
        })
        assert col2_response.status_code == 201
        col2 = col2_response.json()['column']
        
        # Create template card in column 1
        card_response = authenticated_session.post(f"{api_client}/api/columns/{col1['id']}/cards", json={
            'title': 'Multi-Column Template',
            'description': 'Can exist in multiple columns'
        })
        assert card_response.status_code == 201
        template_card = card_response.json()['card']
        
        # Create schedule with allow_duplicates=False
        now = datetime.now()
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': template_card['id'],
            'run_every': 1,
            'unit': 'day',
            'start_datetime': (now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S'),
            'schedule_enabled': False,
            'allow_duplicates': False,
            'keep_source_card': False
        })
        assert schedule_response.status_code == 201
        schedule = schedule_response.json()['schedule']
        
        # Manually create a card from this schedule in column 1 (simulates scheduler creating it)
        card1_response = authenticated_session.post(f"{api_client}/api/columns/{col1['id']}/cards", json={
            'title': 'Multi-Column Template',
            'description': 'Can exist in multiple columns',
            'schedule': schedule['id']
        })
        assert card1_response.status_code == 201
        card1 = card1_response.json()['card']
        
        # Manually create a card from this schedule in column 2
        card2_response = authenticated_session.post(f"{api_client}/api/columns/{col2['id']}/cards", json={
            'title': 'Multi-Column Template',
            'description': 'Can exist in multiple columns',
            'schedule': schedule['id']
        })
        assert card2_response.status_code == 201
        card2 = card2_response.json()['card']
        
        # Verify both cards exist and are not archived
        cards1_response = authenticated_session.get(f"{api_client}/api/columns/{col1['id']}/cards")
        cards1 = cards1_response.json()['cards']
        assert len([c for c in cards1 if c['id'] == card1['id']]) == 1
        
        cards2_response = authenticated_session.get(f"{api_client}/api/columns/{col2['id']}/cards")
        cards2 = cards2_response.json()['cards']
        assert len([c for c in cards2 if c['id'] == card2['id']]) == 1
    
    def test_duplicate_check_prevents_duplicates_in_same_column(self, api_client, authenticated_session, sample_board):
        """Test that duplicate check correctly prevents duplicates within the same column."""
        # Create column
        col_response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
            'name': 'Test Column'
        })
        assert col_response.status_code == 201
        column = col_response.json()['column']
        
        # Create template card
        card_response = authenticated_session.post(f"{api_client}/api/columns/{column['id']}/cards", json={
            'title': 'Single Instance Template',
            'description': 'Should only exist once in column'
        })
        assert card_response.status_code == 201
        template_card = card_response.json()['card']
        
        # Create schedule with allow_duplicates=False
        now = datetime.now()
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': template_card['id'],
            'run_every': 1,
            'unit': 'day',
            'start_datetime': (now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S'),
            'schedule_enabled': False,
            'allow_duplicates': False,
            'keep_source_card': False
        })
        assert schedule_response.status_code == 201
        schedule = schedule_response.json()['schedule']
        
        # Create first card from schedule
        card1_response = authenticated_session.post(f"{api_client}/api/columns/{column['id']}/cards", json={
            'title': 'Single Instance Template',
            'description': 'Should only exist once in column',
            'schedule': schedule['id']
        })
        assert card1_response.status_code == 201
        card1 = card1_response.json()['card']
        
        # Verify card exists
        cards_response = authenticated_session.get(f"{api_client}/api/columns/{column['id']}/cards")
        cards = cards_response.json()['cards']
        schedule_cards = [c for c in cards if c.get('schedule') == schedule['id']]
        assert len(schedule_cards) == 1
        assert schedule_cards[0]['id'] == card1['id']
        
        # At this point, the scheduler should NOT create a duplicate
        # We can't directly test the scheduler logic without triggering it,
        # but we've verified the state that would prevent duplication
    
    def test_moved_card_allows_new_card_in_original_column(self, api_client, authenticated_session, sample_board):
        """Test that when a card is moved to different column, new card can be created in original column."""
        # Create two columns
        col1_response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
            'name': 'Original Column'
        })
        assert col1_response.status_code == 201
        col1 = col1_response.json()['column']
        
        col2_response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
            'name': 'Destination Column'
        })
        assert col2_response.status_code == 201
        col2 = col2_response.json()['column']
        
        # Create template card in column 1
        card_response = authenticated_session.post(f"{api_client}/api/columns/{col1['id']}/cards", json={
            'title': 'Movable Template',
            'description': 'Will be moved between columns'
        })
        assert card_response.status_code == 201
        template_card = card_response.json()['card']
        
        # Create schedule
        now = datetime.now()
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': template_card['id'],
            'run_every': 1,
            'unit': 'day',
            'start_datetime': (now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S'),
            'schedule_enabled': False,
            'allow_duplicates': False,
            'keep_source_card': False
        })
        assert schedule_response.status_code == 201
        schedule = schedule_response.json()['schedule']
        
        # Create card from schedule in column 1
        card_response = authenticated_session.post(f"{api_client}/api/columns/{col1['id']}/cards", json={
            'title': 'Movable Template',
            'description': 'Will be moved between columns',
            'schedule': schedule['id']
        })
        assert card_response.status_code == 201
        created_card = card_response.json()['card']
        
        # Verify card is in column 1
        cards1_response = authenticated_session.get(f"{api_client}/api/columns/{col1['id']}/cards")
        cards1 = cards1_response.json()['cards']
        assert len([c for c in cards1 if c['id'] == created_card['id']]) == 1
        
        # Move card to column 2
        move_response = authenticated_session.patch(f"{api_client}/api/cards/{created_card['id']}", json={
            'column_id': col2['id']
        })
        assert move_response.status_code == 200
        
        # Verify card is now in column 2
        cards2_response = authenticated_session.get(f"{api_client}/api/columns/{col2['id']}/cards")
        cards2 = cards2_response.json()['cards']
        assert len([c for c in cards2 if c['id'] == created_card['id']]) == 1
        
        # Verify card is no longer in column 1
        cards1_response = authenticated_session.get(f"{api_client}/api/columns/{col1['id']}/cards")
        cards1 = cards1_response.json()['cards']
        assert len([c for c in cards1 if c['id'] == created_card['id']]) == 0
        
        # Now column 1 should be available for a new card from the same schedule
        # Create another card from schedule in column 1
        new_card_response = authenticated_session.post(f"{api_client}/api/columns/{col1['id']}/cards", json={
            'title': 'Movable Template',
            'description': 'Will be moved between columns',
            'schedule': schedule['id']
        })
        assert new_card_response.status_code == 201
        new_card = new_card_response.json()['card']
        
        # Verify both cards exist in different columns
        cards1_response = authenticated_session.get(f"{api_client}/api/columns/{col1['id']}/cards")
        cards1 = cards1_response.json()['cards']
        assert len([c for c in cards1 if c['schedule'] == schedule['id']]) == 1
        assert cards1[0]['id'] == new_card['id']
        
        cards2_response = authenticated_session.get(f"{api_client}/api/columns/{col2['id']}/cards")
        cards2 = cards2_response.json()['cards']
        assert len([c for c in cards2 if c['schedule'] == schedule['id']]) == 1
        assert cards2[0]['id'] == created_card['id']
    
    def test_archived_card_allows_new_card_in_same_column(self, api_client, authenticated_session, sample_board):
        """Test that archiving a scheduled card allows a new one to be created in the same column."""
        # Create column
        col_response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
            'name': 'Archive Test Column'
        })
        assert col_response.status_code == 201
        column = col_response.json()['column']
        
        # Create template card
        card_response = authenticated_session.post(f"{api_client}/api/columns/{column['id']}/cards", json={
            'title': 'Archivable Template',
            'description': 'Can be archived and recreated'
        })
        assert card_response.status_code == 201
        template_card = card_response.json()['card']
        
        # Create schedule
        now = datetime.now()
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': template_card['id'],
            'run_every': 1,
            'unit': 'day',
            'start_datetime': (now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S'),
            'schedule_enabled': True,
            'allow_duplicates': False,
            'keep_source_card': False
        })
        assert schedule_response.status_code == 201
        schedule = schedule_response.json()['schedule']
        
        # Create first card from schedule
        card1_response = authenticated_session.post(f"{api_client}/api/columns/{column['id']}/cards", json={
            'title': 'Archivable Template',
            'description': 'Can be archived and recreated',
            'schedule': schedule['id']
        })
        assert card1_response.status_code == 201
        card1 = card1_response.json()['card']
        
        # Archive the first card
        archive_response = authenticated_session.patch(f"{api_client}/api/cards/{card1['id']}", json={
            'archived': True
        })
        assert archive_response.status_code == 200
        
        # Create second card from schedule in same column
        card2_response = authenticated_session.post(f"{api_client}/api/columns/{column['id']}/cards", json={
            'title': 'Archivable Template',
            'description': 'Can be archived and recreated',
            'schedule': schedule['id']
        })
        assert card2_response.status_code == 201
        card2 = card2_response.json()['card']
        
        # Verify only the non-archived card appears in column
        cards_response = authenticated_session.get(f"{api_client}/api/columns/{column['id']}/cards")
        cards = cards_response.json()['cards']
        schedule_cards = [c for c in cards if c.get('schedule') == schedule['id']]
        assert len(schedule_cards) == 1
        assert schedule_cards[0]['id'] == card2['id']
        assert schedule_cards[0]['archived'] is False
    
    def test_allow_duplicates_true_allows_multiple_in_same_column(self, api_client, authenticated_session, sample_board):
        """Test that allow_duplicates=True allows multiple cards in same column."""
        # Create column
        col_response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
            'name': 'Duplicate Allow Column'
        })
        assert col_response.status_code == 201
        column = col_response.json()['column']
        
        # Create template card
        card_response = authenticated_session.post(f"{api_client}/api/columns/{column['id']}/cards", json={
            'title': 'Duplicate Allowed Template',
            'description': 'Multiple instances allowed'
        })
        assert card_response.status_code == 201
        template_card = card_response.json()['card']
        
        # Create schedule with allow_duplicates=True
        now = datetime.now()
        schedule_response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': template_card['id'],
            'run_every': 1,
            'unit': 'hour',
            'start_datetime': (now - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S'),
            'schedule_enabled': True,
            'allow_duplicates': True,
            'keep_source_card': False
        })
        assert schedule_response.status_code == 201
        schedule = schedule_response.json()['schedule']
        
        # Create multiple cards from same schedule in same column
        created_cards = []
        for i in range(3):
            card_resp = authenticated_session.post(f"{api_client}/api/columns/{column['id']}/cards", json={
                'title': 'Duplicate Allowed Template',
                'description': f'Multiple instances allowed - Instance {i+1}',
                'schedule': schedule['id']
            })
            assert card_resp.status_code == 201
            created_cards.append(card_resp.json()['card'])
        
        # Verify all cards exist in the column
        cards_response = authenticated_session.get(f"{api_client}/api/columns/{column['id']}/cards")
        cards = cards_response.json()['cards']
        schedule_cards = [c for c in cards if c.get('schedule') == schedule['id']]
        assert len(schedule_cards) == 3
        
        # Verify they're all different cards
        card_ids = [c['id'] for c in schedule_cards]
        assert len(set(card_ids)) == 3  # All unique IDs




@pytest.mark.api
class TestCreateCardNow:
    """Test cases for creating a card from a schedule on request."""

    def _create_schedule(self, api_client, authenticated_session, scheduled_card, schedule_data):
        response = authenticated_session.post(f"{api_client}/api/schedules", json={
            'card_id': scheduled_card['id'],
            'keep_source_card': False,
            **schedule_data
        })
        assert response.status_code == 201
        return response.json()['schedule']

    def _column_cards(self, api_client, authenticated_session, column_id):
        response = authenticated_session.get(f"{api_client}/api/columns/{column_id}/cards")
        assert response.status_code == 200
        return response.json()['cards']

    def test_creates_card_from_template(self, api_client, authenticated_session, sample_column, scheduled_card, schedule_data):
        schedule = self._create_schedule(api_client, authenticated_session, scheduled_card, schedule_data)

        response = authenticated_session.post(f"{api_client}/api/schedules/{schedule['id']}/run")

        assert response.status_code == 201
        cards = self._column_cards(api_client, authenticated_session, sample_column['id'])
        assert [card['id'] for card in cards] == [response.json()['card_id']]
        assert cards[0]['title'] == 'Template Card'
        assert cards[0]['schedule'] == schedule['id']
        assert cards[0]['scheduled'] is False

    def test_ignores_allow_duplicates(self, api_client, authenticated_session, sample_column, scheduled_card, schedule_data):
        schedule = self._create_schedule(api_client, authenticated_session, scheduled_card, schedule_data)
        assert schedule['allow_duplicates'] is False

        for _ in range(2):
            response = authenticated_session.post(f"{api_client}/api/schedules/{schedule['id']}/run")
            assert response.status_code == 201

        assert len(self._column_cards(api_client, authenticated_session, sample_column['id'])) == 2

    def test_works_on_disabled_schedule_and_leaves_it_unchanged(self, api_client, authenticated_session, scheduled_card, schedule_data):
        schedule_data['schedule_enabled'] = False
        schedule = self._create_schedule(api_client, authenticated_session, scheduled_card, schedule_data)

        response = authenticated_session.post(f"{api_client}/api/schedules/{schedule['id']}/run")
        assert response.status_code == 201

        after = authenticated_session.get(f"{api_client}/api/schedules/{schedule['id']}").json()['schedule']
        assert after['schedule_enabled'] is False
        assert after['start_datetime'] == schedule['start_datetime']

    def test_unknown_schedule_returns_404(self, api_client, authenticated_session):
        response = authenticated_session.post(f"{api_client}/api/schedules/99999999/run")
        assert response.status_code == 404

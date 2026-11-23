"""Tests for checklist item API endpoints."""
import pytest


@pytest.mark.api
class TestChecklistItemsAPI:
    """Test cases for checklist item API endpoints."""
    
    def test_create_checklist_item(self, api_client, authenticated_session, sample_card):
        """Test creating a new checklist item."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Review documentation'}
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['checklist_item']['name'] == 'Review documentation'
        assert data['checklist_item']['card_id'] == sample_card['id']
        assert data['checklist_item']['checked'] is False
        assert 'order' in data['checklist_item']
        assert 'created_at' in data['checklist_item']
        assert 'updated_at' in data['checklist_item']
    
    def test_create_checklist_item_with_checked(self, api_client, authenticated_session, sample_card):
        """Test creating a checklist item with checked status."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Completed task', 'checked': True}
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['checklist_item']['checked'] is True
    
    def test_create_checklist_item_missing_name(self, api_client, authenticated_session, sample_card):
        """Test creating a checklist item without name fails."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'name' in data['message'].lower() or 'required' in data['message'].lower()
    
    def test_create_checklist_item_empty_name(self, api_client, authenticated_session, sample_card):
        """Test creating a checklist item with empty name fails."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': '   '}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_checklist_item_name_too_long(self, api_client, authenticated_session, sample_card):
        """Test creating a checklist item with name exceeding max length."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'x' * 501}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_checklist_item_invalid_card(self, api_client, authenticated_session):
        """Test creating a checklist item for non-existent card fails."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/99999/checklist-items',
            json={'name': 'Test item'}
        )
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
    
    def test_update_checklist_item_name(self, api_client, authenticated_session, sample_card):
        """Test updating a checklist item's name."""
        # Create item first
        create_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Original name'}
        )
        item_id = create_response.json()['checklist_item']['id']
        
        # Update name
        response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/{item_id}',
            json={'name': 'Updated name'}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['checklist_item']['name'] == 'Updated name'
    
    def test_update_checklist_item_checked(self, api_client, authenticated_session, sample_card):
        """Test updating a checklist item's checked status."""
        # Create item first
        create_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Test item'}
        )
        item_id = create_response.json()['checklist_item']['id']
        
        # Update checked status
        response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/{item_id}',
            json={'checked': True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['checklist_item']['checked'] is True
    
    def _create_items(self, api_client, session, card_id, names):
        ids = []
        for name in names:
            response = session.post(
                f'{api_client}/api/cards/{card_id}/checklist-items',
                json={'name': name}
            )
            assert response.status_code == 201
            ids.append(response.json()['checklist_item']['id'])
        return ids

    def _items_in_order(self, api_client, session, card_id):
        response = session.get(f'{api_client}/api/cards/{card_id}')
        assert response.status_code == 200
        items = sorted(response.json()['card']['checklist_items'], key=lambda x: x['order'])
        return [item['name'] for item in items], [item['order'] for item in items]

    def test_update_checklist_item_order(self, api_client, authenticated_session, sample_card):
        """Moving an item up shifts the others, leaving unique positions (#704)."""
        card_id = sample_card['id']
        ids = self._create_items(api_client, authenticated_session, card_id, ['A', 'B', 'C'])

        response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/{ids[2]}',
            json={'order': 0}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['checklist_item']['order'] == 0

        names, orders = self._items_in_order(api_client, authenticated_session, card_id)
        assert names == ['C', 'A', 'B']
        assert orders == [0, 1, 2]

    def test_update_checklist_item_order_moving_down(self, api_client, authenticated_session, sample_card):
        """Moving an item down shifts the items it passes up by one."""
        card_id = sample_card['id']
        ids = self._create_items(api_client, authenticated_session, card_id, ['A', 'B', 'C', 'D'])

        response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/{ids[0]}',
            json={'order': 2}
        )
        assert response.status_code == 200
        assert response.json()['checklist_item']['order'] == 2

        names, orders = self._items_in_order(api_client, authenticated_session, card_id)
        assert names == ['B', 'C', 'A', 'D']
        assert orders == [0, 1, 2, 3]

    def test_update_checklist_item_order_past_end_moves_last(self, api_client, authenticated_session, sample_card):
        """An order past the last position puts the item last, without a gap."""
        card_id = sample_card['id']
        ids = self._create_items(api_client, authenticated_session, card_id, ['A', 'B', 'C'])

        response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/{ids[0]}',
            json={'order': 50}
        )
        assert response.status_code == 200
        assert response.json()['checklist_item']['order'] == 2

        names, orders = self._items_in_order(api_client, authenticated_session, card_id)
        assert names == ['B', 'C', 'A']
        assert orders == [0, 1, 2]

    def test_update_checklist_item_order_full_renumber(self, api_client, authenticated_session, sample_card):
        """The UI saves a drag by setting every item's order in turn; that still gives the dragged order."""
        card_id = sample_card['id']
        ids = self._create_items(api_client, authenticated_session, card_id, ['A', 'B', 'C', 'D'])
        new_order = [ids[3], ids[1], ids[0], ids[2]]

        for position, item_id in enumerate(new_order):
            response = authenticated_session.patch(
                f'{api_client}/api/checklist-items/{item_id}',
                json={'order': position}
            )
            assert response.status_code == 200

        names, orders = self._items_in_order(api_client, authenticated_session, card_id)
        assert names == ['D', 'B', 'A', 'C']
        assert orders == [0, 1, 2, 3]
    
    def test_update_checklist_item_not_found(self, api_client, authenticated_session):
        """Test updating non-existent checklist item fails."""
        response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/99999',
            json={'name': 'Updated name'}
        )
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
    
    def test_update_checklist_item_no_data(self, api_client, authenticated_session, sample_card):
        """Test updating checklist item with no data fails."""
        # Create item first
        create_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Test item'}
        )
        item_id = create_response.json()['checklist_item']['id']
        
        # Update with no data
        response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/{item_id}',
            json={}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_delete_checklist_item(self, api_client, authenticated_session, sample_card):
        """Test deleting a checklist item."""
        # Create item first
        create_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Item to delete'}
        )
        item_id = create_response.json()['checklist_item']['id']
        
        # Delete item
        response = authenticated_session.delete(f'{api_client}/api/checklist-items/{item_id}')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Verify deletion
        get_response = authenticated_session.get(f'{api_client}/api/columns/{sample_card["column_id"]}/cards')
        cards_data = get_response.json()
        card = next((c for c in cards_data['cards'] if c['id'] == sample_card['id']), None)
        if card:
            assert len(card['checklist_items']) == 0
    
    def test_delete_checklist_item_not_found(self, api_client, authenticated_session):
        """Test deleting non-existent checklist item fails."""
        response = authenticated_session.delete(f'{api_client}/api/checklist-items/99999')
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
    
    def test_checklist_items_in_card_response(self, api_client, authenticated_session, sample_card):
        """Test that checklist items are included in card responses."""
        # Create a checklist item
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Test checklist item'}
        )
        
        # Get cards and verify checklist items are included
        response = authenticated_session.get(f'{api_client}/api/columns/{sample_card["column_id"]}/cards')
        assert response.status_code == 200
        data = response.json()
        assert len(data['cards']) > 0
        card = data['cards'][0]
        assert 'checklist_items' in card
        assert len(card['checklist_items']) == 1
        assert card['checklist_items'][0]['name'] == 'Test checklist item'
    
    def test_checklist_item_cascade_delete_with_card(self, api_client, authenticated_session, sample_card):
        """Test that checklist items are deleted when card is deleted."""
        # Create a checklist item
        create_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Test item'}
        )
        item_id = create_response.json()['checklist_item']['id']
        
        # Delete the card
        authenticated_session.delete(f'{api_client}/api/cards/{sample_card["id"]}')
        
        # Verify checklist item is also deleted (attempting to update should fail)
        update_response = authenticated_session.patch(
            f'{api_client}/api/checklist-items/{item_id}',
            json={'name': 'Updated'}
        )
        assert update_response.status_code == 404

    def test_create_checklist_item_at_specific_position(self, api_client, authenticated_session, sample_card):
        """Test creating checklist items at specific positions with proper order shifting."""
        card_id = sample_card['id']
        
        # Create initial checklist items at positions 0, 1, 2
        for i in range(3):
            response = authenticated_session.post(
                f'{api_client}/api/cards/{card_id}/checklist-items',
                json={'name': f'Item {i}', 'order': i}
            )
            assert response.status_code == 201
        
        # Verify initial order
        response = authenticated_session.get(f'{api_client}/api/cards/{card_id}')
        card = response.json()['card']
        items = sorted(card['checklist_items'], key=lambda x: x['order'])
        assert len(items) == 3
        assert [item['name'] for item in items] == ['Item 0', 'Item 1', 'Item 2']
        assert [item['order'] for item in items] == [0, 1, 2]
        
        # Insert new item at position 1 (should shift Item 1 and Item 2)
        response = authenticated_session.post(
            f'{api_client}/api/cards/{card_id}/checklist-items',
            json={'name': 'Inserted at 1', 'order': 1}
        )
        assert response.status_code == 201
        
        # Verify order after insertion at position 1
        response = authenticated_session.get(f'{api_client}/api/cards/{card_id}')
        card = response.json()['card']
        items = sorted(card['checklist_items'], key=lambda x: x['order'])
        assert len(items) == 4
        assert [item['name'] for item in items] == ['Item 0', 'Inserted at 1', 'Item 1', 'Item 2']
        assert [item['order'] for item in items] == [0, 1, 2, 3]
        
        # Insert another item at position 0 (should shift everything)
        response = authenticated_session.post(
            f'{api_client}/api/cards/{card_id}/checklist-items',
            json={'name': 'Inserted at 0', 'order': 0}
        )
        assert response.status_code == 201
        
        # Verify order after insertion at position 0
        response = authenticated_session.get(f'{api_client}/api/cards/{card_id}')
        card = response.json()['card']
        items = sorted(card['checklist_items'], key=lambda x: x['order'])
        assert len(items) == 5
        assert [item['name'] for item in items] == [
            'Inserted at 0', 'Item 0', 'Inserted at 1', 'Item 1', 'Item 2'
        ]
        assert [item['order'] for item in items] == [0, 1, 2, 3, 4]
        
        # Insert at position 3 (middle of list)
        response = authenticated_session.post(
            f'{api_client}/api/cards/{card_id}/checklist-items',
            json={'name': 'Inserted at 3', 'order': 3}
        )
        assert response.status_code == 201
        
        # Verify order after insertion at position 3
        response = authenticated_session.get(f'{api_client}/api/cards/{card_id}')
        card = response.json()['card']
        items = sorted(card['checklist_items'], key=lambda x: x['order'])
        assert len(items) == 6
        assert [item['name'] for item in items] == [
            'Inserted at 0', 'Item 0', 'Inserted at 1', 'Inserted at 3', 'Item 1', 'Item 2'
        ]
        assert [item['order'] for item in items] == [0, 1, 2, 3, 4, 5]
        
        # Insert at end without specifying order (should append)
        response = authenticated_session.post(
            f'{api_client}/api/cards/{card_id}/checklist-items',
            json={'name': 'Appended'}
        )
        assert response.status_code == 201
        
        # Verify it was appended at the end
        response = authenticated_session.get(f'{api_client}/api/cards/{card_id}')
        card = response.json()['card']
        items = sorted(card['checklist_items'], key=lambda x: x['order'])
        assert len(items) == 7
        assert items[-1]['name'] == 'Appended'
        assert items[-1]['order'] == 6

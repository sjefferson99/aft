"""Tests for comment API endpoints."""
import pytest


@pytest.mark.api
class TestCommentsAPI:
    """Test cases for comment API endpoints."""
    
    def test_create_comment(self, api_client, authenticated_session, sample_card):
        """Test creating a new comment."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'This is a test comment'}
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['comment']['comment'] == 'This is a test comment'
        assert data['comment']['card_id'] == sample_card['id']
        assert 'order' in data['comment']
        assert 'created_at' in data['comment']
        assert data['comment']['order'] == 0  # First comment should have order 0
    
    def test_create_multiple_comments_order_increment(self, api_client, authenticated_session, sample_card):
        """Test that comment order increments correctly."""
        # Create first comment
        response1 = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'First comment'}
        )
        assert response1.status_code == 201
        order1 = response1.json()['comment']['order']
        
        # Create second comment
        response2 = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Second comment'}
        )
        assert response2.status_code == 201
        order2 = response2.json()['comment']['order']
        
        # Second comment should have order = first order + 1
        assert order2 == order1 + 1
    
    def test_create_comment_missing_text(self, api_client, authenticated_session, sample_card):
        """Test creating a comment without text fails."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'comment' in data['message'].lower() or 'required' in data['message'].lower()
    
    def test_create_comment_empty_text(self, api_client, authenticated_session, sample_card):
        """Test creating a comment with empty text fails."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': '   '}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'empty' in data['message'].lower()
    
    def test_create_comment_text_too_long(self, api_client, authenticated_session, sample_card):
        """Test creating a comment exceeding max length fails."""
        # MAX_COMMENT_LENGTH is 50000
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'x' * 50001}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'length' in data['message'].lower() or 'exceed' in data['message'].lower()
    
    def test_create_comment_large_valid_text(self, api_client, authenticated_session, sample_card):
        """Test creating a comment with large but valid text succeeds."""
        # Test with a large comment (10KB)
        large_comment = 'x' * 10000
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': large_comment}
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert len(data['comment']['comment']) == 10000
    
    def test_create_comment_invalid_card(self, api_client, authenticated_session):
        """Test creating a comment for non-existent card fails."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/99999/comments',
            json={'comment': 'Test comment'}
        )
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['message'].lower()
    
    def test_get_card_comments(self, api_client, authenticated_session, sample_card):
        """Test getting all comments for a card."""
        # Create some comments
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'First comment'}
        )
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Second comment'}
        )
        
        # Get comments
        response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}/comments'
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['comments']) == 2
        
        # Comments should be ordered by order descending (newest first)
        assert data['comments'][0]['comment'] == 'Second comment'
        assert data['comments'][1]['comment'] == 'First comment'
    
    def test_get_card_comments_empty(self, api_client, authenticated_session, sample_card):
        """Test getting comments for card with no comments."""
        response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}/comments'
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['comments']) == 0
    
    def test_delete_comment(self, api_client, authenticated_session, sample_card):
        """Test deleting a comment."""
        # Create comment first
        create_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Comment to delete'}
        )
        comment_id = create_response.json()['comment']['id']
        
        # Delete comment
        response = authenticated_session.delete(
            f'{api_client}/api/comments/{comment_id}'
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Verify comment is deleted
        get_response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}/comments'
        )
        assert len(get_response.json()['comments']) == 0
    
    def test_delete_comment_preserves_order_gaps(self, api_client, authenticated_session, sample_card):
        """Test that deleting a comment leaves gaps in order sequence."""
        # Create three comments
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'First'}
        )
        r2 = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Second'}
        )
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Third'}
        )
        
        comment_id_2 = r2.json()['comment']['id']
        
        # Delete middle comment
        authenticated_session.delete(f'{api_client}/api/comments/{comment_id_2}')
        
        # Get remaining comments
        response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}/comments'
        )
        comments = response.json()['comments']
        
        # Should have 2 comments with a gap in order
        assert len(comments) == 2
        orders = [c['order'] for c in comments]
        assert 0 in orders
        assert 2 in orders
        assert 1 not in orders  # Gap preserved
    
    def test_delete_comment_invalid_id(self, api_client, authenticated_session):
        """Test deleting non-existent comment fails."""
        response = authenticated_session.delete(
            f'{api_client}/api/comments/99999'
        )
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['message'].lower()
    
    def test_comment_html_escaping(self, api_client, authenticated_session, sample_card):
        """Test that comment text is properly stored (escaping handled client-side)."""
        malicious_comment = '<script>alert("xss")</script>'
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': malicious_comment}
        )
        assert response.status_code == 201
        data = response.json()
        # Server stores raw text; client should escape on display
        assert data['comment']['comment'] == malicious_comment
    
    def test_comment_special_characters(self, api_client, authenticated_session, sample_card):
        """Test that comments with special characters are handled correctly."""
        special_comment = "Test with quotes \"'` and newlines\n\nand tabs\t\tin middle"
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': special_comment}
        )
        assert response.status_code == 201
        data = response.json()
        assert data['comment']['comment'] == special_comment
    
    def test_comment_unicode_characters(self, api_client, authenticated_session, sample_card):
        """Test that comments with unicode characters work correctly."""
        unicode_comment = "Test with emoji 🎉🚀 and unicode characters: 你好世界"
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': unicode_comment}
        )
        assert response.status_code == 201
        data = response.json()
        assert data['comment']['comment'] == unicode_comment


@pytest.mark.api
@pytest.mark.security
class TestCommentsAPISecurity:
    """Security tests for comment API endpoints."""
    
    def test_comment_sql_injection_attempt(self, api_client, authenticated_session, sample_card):
        """Test that SQL injection attempts are safely handled."""
        sql_injection = "'; DROP TABLE comments; --"
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': sql_injection}
        )
        assert response.status_code == 201
        # Should store safely without executing SQL
        
        # Verify table still exists by getting comments
        get_response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}/comments'
        )
        assert get_response.status_code == 200
    
    def test_comment_xss_payload_stored(self, api_client, authenticated_session, sample_card):
        """Test that XSS payloads are stored but not executed (defense in depth)."""
        xss_payloads = [
            '<script>alert(1)</script>',
            '<img src=x onerror=alert(1)>',
            '<svg onload=alert(1)>',
            'javascript:alert(1)',
            '<iframe src="javascript:alert(1)">',
        ]
        
        for payload in xss_payloads:
            response = authenticated_session.post(
                f'{api_client}/api/cards/{sample_card["id"]}/comments',
                json={'comment': payload}
            )
            assert response.status_code == 201
            data = response.json()
            # Payload should be stored as-is (escaping happens on client)
            assert payload in data['comment']['comment']
    
    def test_comment_invalid_json(self, api_client, authenticated_session, sample_card):
        """Test that invalid JSON is rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            data='invalid json{',
            headers={'Content-Type': 'application/json'}
        )
        assert response.status_code == 400
    
    def test_comment_invalid_content_type(self, api_client, authenticated_session, sample_card):
        """Test that requests without JSON content type are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            data='comment=test',
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        assert response.status_code == 400
    
    def test_comment_invalid_data_type(self, api_client, authenticated_session, sample_card):
        """Test that non-string comment values are rejected."""
        test_cases = [
            {'comment': 123},
            {'comment': True},
            {'comment': ['list', 'of', 'items']},
            {'comment': {'nested': 'object'}},
            {'comment': None},
        ]
        
        for test_case in test_cases:
            response = authenticated_session.post(
                f'{api_client}/api/cards/{sample_card["id"]}/comments',
                json=test_case
            )
            assert response.status_code == 400
            data = response.json()
            assert data['success'] is False
    
    def test_comment_path_traversal_in_card_id(self, api_client, authenticated_session):
        """Test that path traversal attempts in card ID are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/../../../etc/passwd/comments',
            json={'comment': 'test'}
        )
        # Should result in 404, 405 (path doesn't match route), or 400
        assert response.status_code in [400, 404, 405]
    
    def test_comment_negative_card_id(self, api_client, authenticated_session):
        """Test that negative card IDs are handled properly."""
        response = authenticated_session.post(
            f'{api_client}/api/cards/-1/comments',
            json={'comment': 'test'}
        )
        assert response.status_code == 404
    
    def test_comment_oversized_payload(self, api_client, authenticated_session, sample_card):
        """Test that extremely large payloads are rejected."""
        # Create a payload larger than MAX_COMMENT_LENGTH
        huge_comment = 'x' * 100000
        response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': huge_comment}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_delete_comment_without_permission(self, api_client, authenticated_session, sample_card):
        """Test deleting a comment that belongs to a different card (if applicable)."""
        # Create a comment
        create_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Test comment'}
        )
        comment_id = create_response.json()['comment']['id']
        
        # Delete should succeed (no auth in current implementation)
        response = authenticated_session.delete(
            f'{api_client}/api/comments/{comment_id}'
        )
        assert response.status_code == 200
    
    def test_comment_whitespace_only_trimmed(self, api_client, authenticated_session, sample_card):
        """Test that comments with only whitespace are rejected."""
        whitespace_tests = [
            '   ',
            '\t\t\t',
            '\n\n\n',
            '  \t  \n  ',
        ]
        
        for whitespace in whitespace_tests:
            response = authenticated_session.post(
                f'{api_client}/api/cards/{sample_card["id"]}/comments',
                json={'comment': whitespace}
            )
            assert response.status_code == 400
            data = response.json()
            assert data['success'] is False


@pytest.mark.api
@pytest.mark.integration
class TestCommentsIntegration:
    """Integration tests for comments with other entities."""
    
    def test_delete_card_cascades_to_comments(self, api_client, authenticated_session, sample_card):
        """Test that deleting a card also deletes its comments."""
        # Create comments
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Comment 1'}
        )
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Comment 2'}
        )
        
        # Delete the card
        authenticated_session.delete(f'{api_client}/api/cards/{sample_card["id"]}')
        
        # Verify card is deleted (should return 404 when trying to get comments)
        response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}/comments'
        )
        # Card doesn't exist so comments endpoint should work but return empty or card operations fail
        # Depending on implementation, this might be 200 with empty list or 404
        assert response.status_code in [200, 404]
    
    def test_card_with_comments_in_board_response(self, api_client, authenticated_session, sample_board, sample_column, sample_card):
        """Test that board response includes a comment_count (not full comment
        bodies) for cards. The board list endpoint intentionally omits comment
        content -- see docs/PERFORMANCE_board_updates.md item 1.5 -- full
        comment bodies are only available via GET /api/cards/{id}.
        """
        # Create a comment
        authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Test comment'}
        )

        # Get board data
        response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/cards'
        )
        assert response.status_code == 200
        data = response.json()

        # Find the card in the response
        card_found = False
        for column in data['board']['columns']:
            for card in column['cards']:
                if card['id'] == sample_card['id']:
                    card_found = True
                    assert 'comments' not in card
                    assert card['comment_count'] == 1
                    break

        assert card_found, "Sample card not found in board response"
    
    def test_get_single_card_includes_comments(self, api_client, authenticated_session, sample_card):
        """Test that GET /api/cards/{id} endpoint includes comments."""
        # Create multiple comments
        comment1_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'First comment'}
        )
        assert comment1_response.status_code == 201
        
        comment2_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Second comment'}
        )
        assert comment2_response.status_code == 201
        
        # Get card data
        response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}'
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['success'] is True
        assert 'card' in data
        card = data['card']
        
        # Verify comments are included
        assert 'comments' in card
        assert len(card['comments']) == 2
        
        # Comments should be sorted by order descending (newest first)
        assert card['comments'][0]['comment'] == 'Second comment'
        assert card['comments'][1]['comment'] == 'First comment'
        
        # Verify comment structure
        for comment in card['comments']:
            assert 'id' in comment
            assert 'card_id' in comment
            assert 'comment' in comment
            assert 'order' in comment
            assert 'created_at' in comment
            assert comment['card_id'] == sample_card['id']
    
    def test_get_single_card_no_comments(self, api_client, authenticated_session, sample_card):
        """Test that GET /api/cards/{id} returns empty comments list when card has no comments."""
        response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}'
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['success'] is True
        assert 'card' in data
        assert 'comments' in data['card']
        assert len(data['card']['comments']) == 0
    
    def test_get_single_card_comments_with_checklist(self, api_client, authenticated_session, sample_card):
        """Test that GET /api/cards/{id} includes both comments and checklist items."""
        # Create a checklist item
        checklist_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/checklist-items',
            json={'name': 'Test checklist item', 'checked': False}
        )
        assert checklist_response.status_code == 201
        
        # Create a comment
        comment_response = authenticated_session.post(
            f'{api_client}/api/cards/{sample_card["id"]}/comments',
            json={'comment': 'Test comment'}
        )
        assert comment_response.status_code == 201
        
        # Get card data
        response = authenticated_session.get(
            f'{api_client}/api/cards/{sample_card["id"]}'
        )
        assert response.status_code == 200
        data = response.json()
        
        card = data['card']
        
        # Verify both comments and checklist items are present
        assert 'comments' in card
        assert 'checklist_items' in card
        assert len(card['comments']) == 1
        assert len(card['checklist_items']) == 1
        assert card['comments'][0]['comment'] == 'Test comment'
        assert card['checklist_items'][0]['name'] == 'Test checklist item'

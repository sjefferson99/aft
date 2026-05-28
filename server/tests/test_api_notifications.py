"""Tests for notification API endpoints."""
import pytest
import requests


@pytest.mark.api
class TestNotificationsAPI:
    """Test cases for notification API endpoints."""
    
    def test_get_notifications_empty(self, api_client, authenticated_session):
        """Test getting notifications when there are none."""
        # Delete any existing notifications via API
        authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        
        response = authenticated_session.get(f'{api_client}/api/notifications')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['notifications'] == []
    
    def test_get_notifications_with_data(self, api_client, authenticated_session, sample_notification):
        """Test getting notifications when they exist."""
        response = authenticated_session.get(f'{api_client}/api/notifications')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['notifications']) >= 1
        
        # Verify structure of returned notification
        notification = data['notifications'][0]
        assert 'id' in notification
        assert 'subject' in notification
        assert 'message' in notification
        assert 'unread' in notification
        assert 'created_at' in notification
    
    def test_get_notifications_sorted_by_newest(self, api_client, authenticated_session):
        """Test that notifications are returned sorted by created_at descending."""
        import time
        
        # Delete existing notifications via API
        authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        
        # Create notifications with time gap
        authenticated_session.post(f'{api_client}/api/notifications', json={
            "subject": "Old Notification",
            "message": "This is old"
        })
        time.sleep(1)  # Ensure different timestamps
        authenticated_session.post(f'{api_client}/api/notifications', json={
            "subject": "New Notification",
            "message": "This is new"
        })
        
        response = authenticated_session.get(f'{api_client}/api/notifications')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True

        # Background services can add unrelated notifications during the test run.
        # Verify the two notifications created here are present and ordered newest-first.
        notifications = data['notifications']
        subjects = [n['subject'] for n in notifications]
        assert "Old Notification" in subjects
        assert "New Notification" in subjects
        assert subjects.index("New Notification") < subjects.index("Old Notification")

        ordered_subjects = [n['subject'] for n in notifications if n['subject'] in {"Old Notification", "New Notification"}]
        assert ordered_subjects == ["New Notification", "Old Notification"]
    
    def test_create_notification_success(self, api_client, authenticated_session):
        """Test creating a notification with valid data."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test Subject",
                "message": "Test message content"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        assert 'Notification created' in data['message']
        
        # Verify notification was created by fetching it
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        assert get_response.status_code == 200
        notifications = get_response.json()['notifications']
        notification = next(n for n in notifications if n['subject'] == "Test Subject")
        assert notification['message'] == "Test message content"
        assert notification['unread'] is True
    
    def test_create_notification_missing_subject(self, api_client, authenticated_session):
        """Test creating a notification without subject."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "message": "Test message"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'subject' in data['message'].lower()
    
    def test_create_notification_missing_message(self, api_client, authenticated_session):
        """Test creating a notification without message."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test Subject"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'message' in data['message'].lower()
    
    def test_create_notification_empty_subject(self, api_client, authenticated_session):
        """Test creating a notification with empty subject after stripping."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "   ",
                "message": "Test message"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'required' in data['message'].lower()
    
    def test_create_notification_empty_message(self, api_client, authenticated_session):
        """Test creating a notification with empty message after stripping."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test Subject",
                "message": "   "
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'required' in data['message'].lower()
    
    def test_create_notification_subject_too_long(self, api_client, authenticated_session):
        """Test creating a notification with subject exceeding 255 characters."""
        long_subject = "A" * 256
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": long_subject,
                "message": "Test message"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert '255' in data['message']
    
    def test_create_notification_message_too_long(self, api_client, authenticated_session):
        """Test creating a notification with message exceeding 65535 characters."""
        long_message = "A" * 65536
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test Subject",
                "message": long_message
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert '65535' in data['message']
    
    def test_create_notification_subject_max_length(self, api_client, authenticated_session):
        """Test creating a notification with subject at max length (255 chars)."""
        max_subject = "A" * 255
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": max_subject,
                "message": "Test message"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
    
    def test_create_notification_strips_whitespace(self, api_client, authenticated_session):
        """Test that subject and message have leading/trailing whitespace stripped."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "  Test Subject  ",
                "message": "  Test message  "
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next(n for n in notifications if n['subject'] == "Test Subject")
        assert notification['message'] == "Test message"
    
    def test_mark_notification_as_read(self, api_client, authenticated_session, sample_notification):
        """Test marking a notification as read."""
        response = authenticated_session.put(
            f'{api_client}/api/notifications/{sample_notification["id"]}/read'
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Verify it's marked as read
        verify_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = verify_response.json()['notifications']
        notification = next(n for n in notifications if n['id'] == sample_notification['id'])
        assert notification['unread'] is False
    
    def test_mark_notification_as_read_not_found(self, api_client, authenticated_session):
        """Test marking a non-existent notification as read."""
        response = authenticated_session.put(f'{api_client}/api/notifications/9999/read')
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['message'].lower()
    
    def test_mark_notification_as_unread(self, api_client, authenticated_session, sample_notification):
        """Test marking a notification as unread."""
        # First mark it as read
        authenticated_session.put(f'{api_client}/api/notifications/{sample_notification["id"]}/read')
        
        # Now mark it as unread
        response = authenticated_session.put(
            f'{api_client}/api/notifications/{sample_notification["id"]}/unread'
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Verify it's marked as unread
        verify_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = verify_response.json()['notifications']
        notification = next(n for n in notifications if n['id'] == sample_notification['id'])
        assert notification['unread'] is True
    
    def test_mark_notification_as_unread_not_found(self, api_client, authenticated_session):
        """Test marking a non-existent notification as unread."""
        response = authenticated_session.put(f'{api_client}/api/notifications/9999/unread')
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['message'].lower()
    
    def test_delete_notification(self, api_client, authenticated_session, sample_notification):
        """Test deleting a notification."""
        notification_id = sample_notification["id"]
        
        response = authenticated_session.delete(f'{api_client}/api/notifications/{notification_id}')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Verify it's deleted
        verify_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = verify_response.json()['notifications']
        assert not any(n['id'] == notification_id for n in notifications)
    
    def test_delete_notification_not_found(self, api_client, authenticated_session):
        """Test deleting a non-existent notification."""
        response = authenticated_session.delete(f'{api_client}/api/notifications/9999')
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['message'].lower()
    
    def test_mark_all_notifications_as_read(self, api_client, authenticated_session):
        """Test marking all notifications as read."""
        # Delete existing and create multiple unread notifications via API
        authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        
        for i in range(3):
            authenticated_session.post(f'{api_client}/api/notifications', json={
                "subject": f"Test Subject {i}",
                "message": f"Test message {i}"
            })
        
        # Mark all as read
        response = authenticated_session.put(f'{api_client}/api/notifications/mark-all-read')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 3
        
        # Verify all are read
        verify_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = verify_response.json()['notifications']
        assert all(not n['unread'] for n in notifications)
    
    def test_mark_all_notifications_as_read_when_none_unread(self, api_client, authenticated_session):
        """Test marking all as read when there are no unread notifications."""
        # Delete existing, create notification, and mark it as read via API
        authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        
        create_response = authenticated_session.post(f'{api_client}/api/notifications', json={
            "subject": "Test Subject",
            "message": "Test message"
        })
        assert create_response.status_code == 201
        
        # Get the notification ID by fetching all notifications
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        assert get_response.status_code == 200
        notifications = get_response.json()['notifications']
        notification_id = notifications[0]['id']
        
        authenticated_session.put(f'{api_client}/api/notifications/{notification_id}/read')
        
        response = authenticated_session.put(f'{api_client}/api/notifications/mark-all-read')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 0
    
    def test_delete_all_notifications(self, api_client, authenticated_session):
        """Test deleting all notifications."""
        # Delete existing and create multiple notifications via API
        authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        
        for i in range(3):
            authenticated_session.post(f'{api_client}/api/notifications', json={
                "subject": f"Test Subject {i}",
                "message": f"Test message {i}"
            })
        
        # Delete all
        response = authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 3
        
        # Verify all are deleted
        verify_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = verify_response.json()['notifications']
        assert len(notifications) == 0
    
    def test_delete_all_notifications_when_empty(self, api_client, authenticated_session):
        """Test deleting all notifications when there are none."""
        # Ensure empty via API
        authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        
        response = authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 0


@pytest.mark.api
class TestNotificationsEdgeCases:
    """Edge case tests for notification API endpoints."""
    
    def test_create_notification_with_special_characters(self, api_client, authenticated_session):
        """Test creating a notification with special characters."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test <script>alert('xss')</script>",
                "message": "Message with 'quotes' and \"double quotes\" & ampersand"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next(n for n in notifications if "<script>" in n['subject'])
        assert "'" in notification['message']
    
    def test_create_notification_with_unicode(self, api_client, authenticated_session):
        """Test creating a notification with unicode characters."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test 😀 Emoji",
                "message": "Unicode: ñ, é, ü, 中文, العربية"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next(n for n in notifications if "😀" in n['subject'])
        assert "中文" in notification['message']
    
    def test_create_notification_with_newlines(self, api_client, authenticated_session):
        """Test creating a notification with newline characters."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test Subject",
                "message": "Line 1\nLine 2\nLine 3"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next(n for n in notifications if n['message'].startswith("Line 1"))
        assert "\n" in notification['message']
    
    def test_concurrent_mark_as_read(self, api_client, authenticated_session, sample_notification):
        """Test marking the same notification as read concurrently."""
        notification_id = sample_notification["id"]
        
        # Make multiple simultaneous requests
        import concurrent.futures
        auth_cookies = authenticated_session.cookies.get_dict()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(
                    requests.put,
                    f'{api_client}/api/notifications/{notification_id}/read',
                    cookies=auth_cookies
                )
                for _ in range(3)
            ]
            results = [f.result() for f in futures]
        
        # All should succeed
        assert all(r.status_code == 200 for r in results)
        
        # Verify it's read
        verify_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = verify_response.json()['notifications']
        notification = next(n for n in notifications if n['id'] == notification_id)
        assert notification['unread'] is False
    
    def test_notification_with_exact_max_lengths(self, api_client, authenticated_session):
        """Test notification with exactly maximum allowed lengths."""
        max_subject = "X" * 255
        max_message = "Y" * 65535
        
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": max_subject,
                "message": max_message
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1


@pytest.mark.api
class TestNotificationsSecurity:
    """Security tests for notification API endpoints."""
    
    def test_create_notification_sql_injection_attempt(self, api_client, authenticated_session):
        """Test that SQL injection attempts are handled safely."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "'; DROP TABLE notifications; --",
                "message": "1' OR '1'='1"
            }
        )
        # Should create successfully (SQLAlchemy protects against SQL injection)
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        
        # Verify notifications table still exists
        verify_response = authenticated_session.get(f'{api_client}/api/notifications')
        assert verify_response.status_code == 200
    
    def test_create_notification_no_internal_error_leak(self, api_client, authenticated_session):
        """Test that internal errors don't leak implementation details."""
        # Test with extremely long input that might cause internal errors
        massive_string = "A" * 1000000  # 1MB string
        
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": massive_string,
                "message": massive_string
            }
        )
        
        # Should return an error without leaking details
        assert response.status_code in [400, 500]
        data = response.json()
        assert data['success'] is False
        # Should not contain database-specific error details
        message = data['message'].lower()
        assert 'sqlalchemy' not in message
        assert 'traceback' not in message
        assert 'exception' not in message
    
    def test_invalid_notification_id_type(self, api_client, authenticated_session):
        """Test using invalid ID types in endpoints."""
        invalid_ids = ['abc', '1.5', 'null', '<script>']
        
        for invalid_id in invalid_ids:
            response = authenticated_session.delete(f'{api_client}/api/notifications/{invalid_id}')
            # Should handle gracefully (404 or 400)
            assert response.status_code in [400, 404]
            data = response.json()
            assert data['success'] is False
    
    def test_create_notification_subject_exceeds_limit(self, api_client, authenticated_session):
        """Test creating notification with subject exceeding 255 char limit is rejected."""
        # Create subject longer than 255 chars
        subject = "A" * 300
        message = "Test message for validation"
        
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            "subject": subject,
            "message": message
        })
        
        # API should reject oversized input
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'Subject must be 255 characters or less' in data['message']
    
    def test_create_notification_message_exceeds_limit(self, api_client, authenticated_session):
        """Test creating notification with message exceeding 65535 char limit is rejected."""
        subject = "Test Validation"
        # Create message longer than 65535 chars
        message = "B" * 70000
        
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            "subject": subject,
            "message": message
        })
        
        # API should reject oversized input
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'Message must be 65535 characters or less' in data['message']
    
    def test_create_notification_both_exceed_limits(self, api_client, authenticated_session):
        """Test creating notification with both subject and message exceeding limits is rejected."""
        subject = "X" * 300
        message = "Y" * 70000
        
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            "subject": subject,
            "message": message
        })
        
        # API should reject oversized input (validates subject first)
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert '255 characters or less' in data['message']
    
    def test_create_notification_at_exact_limits(self, api_client, authenticated_session):
        """Test creating notification at exact character limits is accepted."""
        subject = "A" * 255
        message = "B" * 65535
        
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            "subject": subject,
            "message": message
        })
        
        # API should accept input at exact limits
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify no truncation occurred by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if len(n['subject']) == 255), None)
        assert notification is not None
        assert len(notification['subject']) == 255
        assert len(notification['message']) == 65535
        assert notification['subject'] == subject
        assert notification['message'] == message


@pytest.mark.api
class TestNotificationActions:
    """Test cases for notification action fields."""
    
    def test_create_notification_with_action(self, api_client, authenticated_session):
        """Test creating a notification with action title and URL."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "New Feature",
                "message": "Check out our new feature!",
                "action_title": "Learn More",
                "action_url": "/features"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n['subject'] == 'New Feature'), None)
        assert notification is not None
        assert notification['action_title'] == "Learn More"
        assert notification['action_url'] == "/features"
    
    def test_create_notification_without_action(self, api_client, authenticated_session):
        """Test creating a notification without action fields."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Simple Notification",
                "message": "Just a message"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n['subject'] == 'Simple Notification'), None)
        assert notification is not None
        assert notification['action_title'] is None
        assert notification['action_url'] is None
    
    def test_create_notification_action_title_too_long(self, api_client, authenticated_session):
        """Test creating a notification with action title exceeding 100 characters."""
        long_title = "A" * 101
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": long_title,
                "action_url": "/test"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert '100' in data['message']
    
    def test_create_notification_action_url_too_long(self, api_client, authenticated_session):
        """Test creating a notification with action URL exceeding 500 characters."""
        long_url = "A" * 501
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": long_url
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert '500' in data['message']
    
    def test_create_notification_action_title_max_length(self, api_client, authenticated_session):
        """Test creating a notification with action title at max length (100 chars)."""
        max_title = "A" * 100
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": max_title,
                "action_url": "/test"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if len(n.get('action_title', '')) == 100), None)
        assert notification is not None
        assert notification['action_title'] == max_title
    
    def test_create_notification_action_url_max_length(self, api_client, authenticated_session):
        """Test creating a notification with action URL at max length (500 chars)."""
        # Create a valid relative URL at max length (500 chars starting with /)
        max_url = "/" + "a" * 499
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": max_url
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if len(n.get('action_url', '')) == 500), None)
        assert notification is not None
        assert notification['action_url'] == max_url
        assert len(notification['action_url']) == 500
    
    def test_create_notification_action_title_strips_whitespace(self, api_client, authenticated_session):
        """Test that action title has whitespace stripped."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "  Click Here  ",
                "action_url": "/test"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n.get('action_title') == 'Click Here'), None)
        assert notification is not None
        assert notification['action_title'] == "Click Here"
    
    def test_create_notification_empty_action_title(self, api_client, authenticated_session):
        """Test creating a notification with empty action title after stripping."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "   ",
                "action_url": "/test"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching - empty action_title should be None
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n['action_url'] == '/test'), None)
        assert notification is not None
        assert notification['action_title'] is None
    
    def test_create_notification_empty_action_url(self, api_client, authenticated_session):
        """Test creating a notification with empty action URL after stripping."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "   "
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching - empty action_url should be None
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n.get('action_title') == 'Click' and n.get('action_url') is None), None)
        assert notification is not None
        assert notification['action_url'] is None
    
    def test_get_notifications_includes_action_fields(self, api_client, authenticated_session):
        """Test that GET /api/notifications includes action fields."""
        # Create notification with action
        authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "View Details",
                "action_url": "/details"
            }
        )
        
        # Get all notifications
        response = authenticated_session.get(f'{api_client}/api/notifications')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        
        # Find our notification
        notification = next(
            (n for n in data['notifications'] if n['subject'] == 'Test'),
            None
        )
        assert notification is not None
        assert notification['action_title'] == "View Details"
        assert notification['action_url'] == "/details"
    
    def test_create_notification_action_title_over_recommended_length(self, api_client, authenticated_session):
        """Test that action title over 50 chars (recommended max) still succeeds but logs warning."""
        # 51 chars (over recommended but under hard limit)
        title = "A" * 51
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": title,
                "action_url": "/test"
            }
        )
        # Should succeed since it's under hard limit of 100
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] ==1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if len(n.get('action_title', '')) == 51), None)
        assert notification is not None
        assert notification['action_title'] == title


@pytest.mark.api
class TestNotificationSecurityURLValidation:
    """Security tests for notification action URL validation."""
    
    def test_create_notification_with_javascript_protocol(self, api_client, authenticated_session):
        """Test that javascript: URLs are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "javascript:alert('XSS')"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'javascript:' in data['message'].lower()
    
    def test_create_notification_with_data_protocol(self, api_client, authenticated_session):
        """Test that data: URLs are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "data:text/html,<script>alert('XSS')</script>"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'data:' in data['message'].lower()
    
    def test_create_notification_with_vbscript_protocol(self, api_client, authenticated_session):
        """Test that vbscript: URLs are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "vbscript:msgbox('XSS')"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'vbscript:' in data['message'].lower()
    
    def test_create_notification_with_file_protocol(self, api_client, authenticated_session):
        """Test that file: URLs are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "file:///etc/passwd"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'file:' in data['message'].lower()
    
    def test_create_notification_with_about_protocol(self, api_client, authenticated_session):
        """Test that about: URLs are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "about:blank"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_notification_with_blob_protocol(self, api_client, authenticated_session):
        """Test that blob: URLs are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "blob:https://example.com/test"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_notification_with_relative_url(self, api_client, authenticated_session):
        """Test that relative URLs starting with / are accepted."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "View Page",
                "action_url": "/settings"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n.get('action_url') == '/settings'), None)
        assert notification is not None
        assert notification['action_url'] == "/settings"
    
    def test_create_notification_with_http_url(self, api_client, authenticated_session):
        """Test that http:// URLs are accepted."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Visit",
                "action_url": "http://example.com"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n.get('action_url') == 'http://example.com'), None)
        assert notification is not None
        assert notification['action_url'] == "http://example.com"
    
    def test_create_notification_with_https_url(self, api_client, authenticated_session):
        """Test that https:// URLs are accepted."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Visit",
                "action_url": "https://example.com"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify by fetching
        get_response = authenticated_session.get(f'{api_client}/api/notifications')
        notifications = get_response.json()['notifications']
        notification = next((n for n in notifications if n.get('action_url') == 'https://example.com'), None)
        assert notification is not None
        assert notification['action_url'] == "https://example.com"
    
    def test_create_notification_with_uppercase_javascript_protocol(self, api_client, authenticated_session):
        """Test that JavaScript: URLs (case variation) are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "JavaScript:alert('XSS')"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_notification_with_mixed_case_data_protocol(self, api_client, authenticated_session):
        """Test that DaTa: URLs (case variation) are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "DaTa:text/html,<script>alert('XSS')</script>"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_notification_with_protocol_only_url(self, api_client, authenticated_session):
        """Test that URLs without proper structure after protocol are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "ftp://test.com"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False

    def test_create_notification_with_attribute_breakout_double_quote(self, api_client, authenticated_session):
        """Test that action_url payloads containing double quotes are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": '/x" onclick="alert(1)" data-x="'
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'invalid action url' in data['message'].lower()

    def test_create_notification_with_attribute_breakout_single_quote(self, api_client, authenticated_session):
        """Test that action_url payloads containing single quotes are rejected."""
        response = authenticated_session.post(
            f'{api_client}/api/notifications',
            json={
                "subject": "Test",
                "message": "Test message",
                "action_title": "Click",
                "action_url": "/x' onclick='alert(1)' data-x='"
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'invalid action url' in data['message'].lower()


@pytest.mark.api
class TestNotificationIDORSecurity:
    """Regression tests for Issue 3: Notification authorization IDOR (cross-user mutation).

    Each test verifies that a request from User B cannot read, mutate, or
    enumerate notifications that belong to User A.
    """

    def test_cannot_mark_other_users_notification_as_read(
        self, api_client, authenticated_session, second_user_session
    ):
        """User B must not be able to mark User A's notification as read."""
        create_resp = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'User A private',
            'message': 'Belongs to user A',
        })
        assert create_resp.status_code == 201
        
        # Get user A's notifications to find the ID
        a_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert a_get_resp.status_code == 200
        a_notifs = a_get_resp.json()['notifications']
        notif_id = next((n['id'] for n in a_notifs if n['subject'] == 'User A private'), None)
        assert notif_id is not None

        response = second_user_session.put(f'{api_client}/api/notifications/{notif_id}/read')
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

        check = authenticated_session.get(f'{api_client}/api/notifications')
        notifs = check.json()['notifications']
        target = next((n for n in notifs if n['id'] == notif_id), None)
        assert target is not None, "User A's notification disappeared"
        assert target['unread'] is True, "Notification was unexpectedly marked read by User B"

    def test_cannot_mark_other_users_notification_as_unread(
        self, api_client, authenticated_session, second_user_session
    ):
        """User B must not be able to mark User A's notification as unread."""
        create_resp = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'User A read notif',
            'message': 'Already read',
        })
        assert create_resp.status_code == 201
        
        # Get user A's notifications to find the ID
        a_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert a_get_resp.status_code == 200
        a_notifs = a_get_resp.json()['notifications']
        notif_id = next((n['id'] for n in a_notifs if n['subject'] == 'User A read notif'), None)
        assert notif_id is not None
        
        authenticated_session.put(f'{api_client}/api/notifications/{notif_id}/read')

        response = second_user_session.put(f'{api_client}/api/notifications/{notif_id}/unread')
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

        check = authenticated_session.get(f'{api_client}/api/notifications')
        notifs = check.json()['notifications']
        target = next((n for n in notifs if n['id'] == notif_id), None)
        assert target is not None, "User A's notification disappeared"
        assert target['unread'] is False, "Notification was unexpectedly flipped to unread by User B"

    def test_cannot_delete_other_users_notification(
        self, api_client, authenticated_session, second_user_session
    ):
        """User B must not be able to delete User A's notification."""
        create_resp = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'Do not delete',
            'message': 'Belongs to user A',
        })
        assert create_resp.status_code == 201
        
        # Get user A's notifications to find the ID
        a_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert a_get_resp.status_code == 200
        a_notifs = a_get_resp.json()['notifications']
        notif_id = next((n['id'] for n in a_notifs if n['subject'] == 'Do not delete'), None)
        assert notif_id is not None

        response = second_user_session.delete(f'{api_client}/api/notifications/{notif_id}')
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

        check = authenticated_session.get(f'{api_client}/api/notifications')
        notifs = check.json()['notifications']
        assert any(n['id'] == notif_id for n in notifs), (
            "User A's notification was deleted by User B"
        )

    def test_mark_all_read_only_affects_own_notifications(
        self, api_client, authenticated_session, second_user_session
    ):
        """User B's mark-all-read must not touch User A's unread notifications."""
        create_resp = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'User A unread',
            'message': 'Should stay unread',
        })
        assert create_resp.status_code == 201
        
        # Get user A's notifications to find the ID
        a_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert a_get_resp.status_code == 200
        a_notifs = a_get_resp.json()['notifications']
        a_notif_id = next((n['id'] for n in a_notifs if n['subject'] == 'User A unread'), None)
        assert a_notif_id is not None

        b_create = second_user_session.post(f'{api_client}/api/notifications', json={
            'subject': 'User B unread',
            'message': 'User B notification',
        })
        assert b_create.status_code == 201

        mark_resp = second_user_session.put(f'{api_client}/api/notifications/mark-all-read')
        assert mark_resp.status_code == 200
        assert mark_resp.json()['count'] == 1, "Expected exactly User B's 1 notification to be updated"

        check = authenticated_session.get(f'{api_client}/api/notifications')
        notifs = check.json()['notifications']
        target = next((n for n in notifs if n['id'] == a_notif_id), None)
        assert target is not None, "User A's notification disappeared"
        assert target['unread'] is True, "User A's notification was marked read by User B's bulk action"

    def test_delete_all_only_affects_own_notifications(
        self, api_client, authenticated_session, second_user_session
    ):
        """User B's delete-all must not delete User A's notifications."""
        create_resp = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'User A must survive',
            'message': 'Should not be deleted',
        })
        assert create_resp.status_code == 201
        
        # Get user A's notifications to find the ID
        a_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert a_get_resp.status_code == 200
        a_notifs = a_get_resp.json()['notifications']
        a_notif_id = next((n['id'] for n in a_notifs if n['subject'] == 'User A must survive'), None)
        assert a_notif_id is not None

        second_user_session.post(f'{api_client}/api/notifications', json={
            'subject': 'User B to delete',
            'message': 'User B notification',
        })
        delete_resp = second_user_session.delete(f'{api_client}/api/notifications/delete-all')
        assert delete_resp.status_code == 200
        assert delete_resp.json()['count'] == 1, "Expected exactly User B's 1 notification to be deleted"

        check = authenticated_session.get(f'{api_client}/api/notifications')
        notifs = check.json()['notifications']
        assert any(n['id'] == a_notif_id for n in notifs), (
            "User A's notification was deleted by User B's delete-all"
        )


@pytest.mark.api
class TestNotificationMultiUserCreation:
    """Test cases for admin creating notifications for all users."""
    
    def test_regular_user_creates_notification_for_self_only(
        self, api_client, second_user_session, authenticated_session
    ):
        """Regular user creating notification should only affect themselves."""
        # Clear all notifications first to ensure clean state
        authenticated_session.delete(f'{api_client}/api/notifications/delete-all')
        second_user_session.delete(f'{api_client}/api/notifications/delete-all')
        
        # Use unique timestamp-based subject to avoid collisions with other tests
        import time
        unique_subject = f'User B notification {int(time.time() * 1000)}'
        
        # Second user creates notification without for_all_users flag
        response = second_user_session.post(f'{api_client}/api/notifications', json={
            'subject': unique_subject,
            'message': 'Should only be for User B',
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify User B sees it
        b_get_resp = second_user_session.get(f'{api_client}/api/notifications')
        assert b_get_resp.status_code == 200
        b_notifs = b_get_resp.json()['notifications']
        assert any(n['subject'] == unique_subject for n in b_notifs), f"User B should see their notification"
        
        # Verify admin does NOT see it
        admin_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert admin_get_resp.status_code == 200
        admin_notifs = admin_get_resp.json()['notifications']
        assert not any(n['subject'] == unique_subject for n in admin_notifs), f"Admin should NOT see User B's notification"
    
    def test_regular_user_cannot_create_for_all_users(
        self, api_client, second_user_session
    ):
        """Regular user should not be able to create notifications for all users."""
        response = second_user_session.post(f'{api_client}/api/notifications', json={
            'subject': 'Attempted broadcast',
            'message': 'Should fail',
            'for_all_users': True
        })
        assert response.status_code == 403
        data = response.json()
        assert data['success'] is False
        assert 'administrator' in data['message'].lower() or 'permission' in data['message'].lower()
    
    def test_admin_creates_notification_for_all_users(
        self, api_client, authenticated_session, second_user_session
    ):
        """Admin should be able to create notification for all users."""
        # Admin creates notification for all users
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'System announcement',
            'message': 'All users should see this',
            'for_all_users': True
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] >= 2  # At least admin and second user
        
        # Verify admin sees it
        admin_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert admin_get_resp.status_code == 200
        admin_notifs = admin_get_resp.json()['notifications']
        assert any(n['subject'] == 'System announcement' for n in admin_notifs)
        
        # Verify second user sees it
        user_get_resp = second_user_session.get(f'{api_client}/api/notifications')
        assert user_get_resp.status_code == 200
        user_notifs = user_get_resp.json()['notifications']
        assert any(n['subject'] == 'System announcement' for n in user_notifs)
    
    def test_admin_creates_notification_for_self_only(
        self, api_client, authenticated_session, second_user_session
    ):
        """Admin can create notification for themselves only."""
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'Admin only note',
            'message': 'Just for me',
            'for_all_users': False
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        
        # Verify admin sees it
        admin_get_resp = authenticated_session.get(f'{api_client}/api/notifications')
        assert admin_get_resp.status_code == 200
        admin_notifs = admin_get_resp.json()['notifications']
        assert any(n['subject'] == 'Admin only note' for n in admin_notifs)
        
        # Verify second user does NOT see it
        user_get_resp = second_user_session.get(f'{api_client}/api/notifications')
        assert user_get_resp.status_code == 200
        user_notifs = user_get_resp.json()['notifications']
        assert not any(n['subject'] == 'Admin only note' for n in user_notifs)
    
    def test_for_all_users_with_action_fields(
        self, api_client, authenticated_session, second_user_session
    ):
        """Admin creating notification for all users with action fields."""
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'Update available',
            'message': 'New version released',
            'for_all_users': True,
            'action_title': 'View Details',
            'action_url': '/updates'
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] >= 2
        
        # Verify both users see it with action fields
        for session in [authenticated_session, second_user_session]:
            get_resp = session.get(f'{api_client}/api/notifications')
            assert get_resp.status_code == 200
            notifs = get_resp.json()['notifications']
            notif = next((n for n in notifs if n['subject'] == 'Update available'), None)
            assert notif is not None
            assert notif['action_title'] == 'View Details'
            assert notif['action_url'] == '/updates'
    
    def test_for_all_users_invalid_type(self, api_client, authenticated_session):
        """Test that for_all_users with invalid type (e.g., string) is rejected."""
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'Test',
            'message': 'Test message',
            'for_all_users': 'false'  # String instead of boolean
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'boolean' in data['message'].lower()
    
    def test_single_user_create_returns_notification_id(self, api_client, authenticated_session):
        """Test that creating notification for single user returns notification_id."""
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'Single user test',
            'message': 'Should return notification_id',
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] == 1
        assert 'notification_id' in data
        assert isinstance(data['notification_id'], int)
        assert 'notification_ids' not in data  # Should not have the array form
    
    def test_multi_user_create_returns_notification_ids(self, api_client, authenticated_session):
        """Test that creating notification for all users returns notification_ids array."""
        response = authenticated_session.post(f'{api_client}/api/notifications', json={
            'subject': 'Multi user test',
            'message': 'Should return notification_ids',
            'for_all_users': True
        })
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] >= 1
        assert 'notification_ids' in data
        assert isinstance(data['notification_ids'], list)
        assert len(data['notification_ids']) == data['count']
        assert 'notification_id' not in data  # Should not have the single form

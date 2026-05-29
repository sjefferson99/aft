"""API tests for branding logo endpoints."""

import requests
import pytest


MAX_LOGO_UPLOAD_BYTES = 100 * 1024


def _reset_logo(api_client, authenticated_session):
    """Reset branding logo to a known default state."""
    response = authenticated_session.delete(f'{api_client}/api/branding/logo')
    assert response.status_code == 200, response.text


def _upload_logo(session, api_client, filename='logo.webp', content=b'logo-bytes', mime='image/webp'):
    """Upload a logo using multipart form data."""
    return session.post(
        f'{api_client}/api/branding/logo',
        files={'image': (filename, content, mime)},
    )


@pytest.mark.api
class TestBrandingAPI:
    """Test branding API endpoints."""

    def test_get_logo_unauthenticated(self, api_client, authenticated_session):
        """Public GET returns null when no custom logo is configured."""
        _reset_logo(api_client, authenticated_session)

        response = requests.get(f'{api_client}/api/branding/logo')
        assert response.status_code == 200
        data = response.json()
        assert data['filename'] is None

    def test_get_logo_authenticated_no_custom(self, api_client, authenticated_session):
        """Authenticated GET returns null when no custom logo is configured."""
        _reset_logo(api_client, authenticated_session)

        response = authenticated_session.get(f'{api_client}/api/branding/logo')
        assert response.status_code == 200
        data = response.json()
        assert data['filename'] is None

    def test_upload_logo_success(self, api_client, authenticated_session):
        """Admin can upload a valid logo and fetch it again."""
        _reset_logo(api_client, authenticated_session)

        response = _upload_logo(
            authenticated_session,
            api_client,
            filename='custom-logo.webp',
            content=b'webp-test-logo',
            mime='image/webp',
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['filename'].startswith('logo_')
        assert data['filename'].endswith('.webp')

        get_response = authenticated_session.get(f'{api_client}/api/branding/logo')
        assert get_response.status_code == 200
        assert get_response.json()['filename'] == data['filename']

        _reset_logo(api_client, authenticated_session)

    def test_upload_logo_too_large(self, api_client, authenticated_session):
        """Uploads larger than 100KB are rejected."""
        _reset_logo(api_client, authenticated_session)

        response = _upload_logo(
            authenticated_session,
            api_client,
            filename='too-large.webp',
            content=b'x' * (MAX_LOGO_UPLOAD_BYTES + 1),
            mime='image/webp',
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert '100KB' in data['message']

    def test_upload_logo_invalid_extension(self, api_client, authenticated_session):
        """Uploads with unsupported extensions are rejected."""
        _reset_logo(api_client, authenticated_session)

        response = _upload_logo(
            authenticated_session,
            api_client,
            filename='not-a-logo.txt',
            content=b'plain-text',
            mime='text/plain',
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'Invalid file type' in data['message']

    def test_upload_logo_no_permission(self, api_client, authenticated_session, second_user_session):
        """Non-admin users cannot upload instance branding."""
        _reset_logo(api_client, authenticated_session)

        response = _upload_logo(
            second_user_session,
            api_client,
            filename='custom-logo.webp',
            content=b'webp-test-logo',
            mime='image/webp',
        )
        assert response.status_code == 403

    def test_reset_logo(self, api_client, authenticated_session):
        """Reset removes the configured custom logo."""
        _reset_logo(api_client, authenticated_session)

        upload_response = _upload_logo(
            authenticated_session,
            api_client,
            filename='custom-logo.webp',
            content=b'webp-test-logo',
            mime='image/webp',
        )
        assert upload_response.status_code == 200, upload_response.text

        reset_response = authenticated_session.delete(f'{api_client}/api/branding/logo')
        assert reset_response.status_code == 200
        reset_data = reset_response.json()
        assert reset_data['success'] is True

        get_response = authenticated_session.get(f'{api_client}/api/branding/logo')
        assert get_response.status_code == 200
        assert get_response.json()['filename'] is None

    def test_reset_logo_no_permission(self, api_client, authenticated_session, second_user_session):
        """Non-admin users cannot reset instance branding."""
        _reset_logo(api_client, authenticated_session)

        upload_response = _upload_logo(
            authenticated_session,
            api_client,
            filename='custom-logo.webp',
            content=b'webp-test-logo',
            mime='image/webp',
        )
        assert upload_response.status_code == 200, upload_response.text

        response = second_user_session.delete(f'{api_client}/api/branding/logo')
        assert response.status_code == 403

        _reset_logo(api_client, authenticated_session)

    def test_get_logo_unauthenticated_after_upload(self, api_client, authenticated_session):
        """Public GET still returns the configured filename after upload."""
        _reset_logo(api_client, authenticated_session)

        upload_response = _upload_logo(
            authenticated_session,
            api_client,
            filename='custom-logo.png',
            content=b'png-test-logo',
            mime='image/png',
        )
        assert upload_response.status_code == 200, upload_response.text
        filename = upload_response.json()['filename']

        get_response = requests.get(f'{api_client}/api/branding/logo')
        assert get_response.status_code == 200
        assert get_response.json()['filename'] == filename

        _reset_logo(api_client, authenticated_session)

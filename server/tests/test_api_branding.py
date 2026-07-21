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


def _reset_app_name(api_client, authenticated_session):
    """Reset PWA app name to the default."""
    response = authenticated_session.delete(f'{api_client}/api/branding/app-name')
    assert response.status_code == 200, response.text


@pytest.mark.api
class TestBrandingAppNameAPI:
    """Test cases for the PWA app name branding endpoints."""

    def test_get_app_name_default(self, api_client, authenticated_session):
        """GET returns the default name when nothing is configured."""
        _reset_app_name(api_client, authenticated_session)

        response = requests.get(f'{api_client}/api/branding/app-name')
        assert response.status_code == 200
        assert response.json()['name'] == 'AFT Tasks'

    def test_set_app_name_success(self, api_client, authenticated_session):
        """Admin can set a custom app name and read it back."""
        _reset_app_name(api_client, authenticated_session)

        response = authenticated_session.put(
            f'{api_client}/api/branding/app-name',
            json={'name': 'AFT - Work'},
        )
        assert response.status_code == 200, response.text
        assert response.json()['name'] == 'AFT - Work'

        get_response = requests.get(f'{api_client}/api/branding/app-name')
        assert get_response.status_code == 200
        assert get_response.json()['name'] == 'AFT - Work'

        _reset_app_name(api_client, authenticated_session)

    def test_set_app_name_empty(self, api_client, authenticated_session):
        """Empty/whitespace-only names are rejected."""
        response = authenticated_session.put(
            f'{api_client}/api/branding/app-name',
            json={'name': '   '},
        )
        assert response.status_code == 400
        assert response.json()['success'] is False

    def test_set_app_name_too_long(self, api_client, authenticated_session):
        """Names longer than the max length are rejected."""
        response = authenticated_session.put(
            f'{api_client}/api/branding/app-name',
            json={'name': 'x' * 46},
        )
        assert response.status_code == 400
        assert response.json()['success'] is False

    def test_set_app_name_no_permission(self, api_client, authenticated_session, second_user_session):
        """Non-admin users cannot set the instance app name."""
        _reset_app_name(api_client, authenticated_session)

        response = second_user_session.put(
            f'{api_client}/api/branding/app-name',
            json={'name': 'Hijacked'},
        )
        assert response.status_code == 403

    def test_reset_app_name(self, api_client, authenticated_session):
        """Reset removes the configured custom app name."""
        set_response = authenticated_session.put(
            f'{api_client}/api/branding/app-name',
            json={'name': 'AFT - Work'},
        )
        assert set_response.status_code == 200, set_response.text

        reset_response = authenticated_session.delete(f'{api_client}/api/branding/app-name')
        assert reset_response.status_code == 200
        assert reset_response.json()['success'] is True

        get_response = requests.get(f'{api_client}/api/branding/app-name')
        assert get_response.status_code == 200
        assert get_response.json()['name'] == 'AFT Tasks'

    def test_reset_app_name_no_permission(self, api_client, authenticated_session, second_user_session):
        """Non-admin users cannot reset the instance app name."""
        response = second_user_session.delete(f'{api_client}/api/branding/app-name')
        assert response.status_code == 403

        _reset_app_name(api_client, authenticated_session)


@pytest.mark.api
class TestPwaManifestAPI:
    """Test cases for the dynamic PWA web app manifest route."""

    def test_manifest_default(self, api_client, authenticated_session):
        """Manifest reflects the default app name and required PWA fields."""
        _reset_app_name(api_client, authenticated_session)

        response = requests.get(f'{api_client}/manifest.webmanifest')
        assert response.status_code == 200
        assert response.headers['Content-Type'].startswith('application/manifest+json')

        data = response.json()
        assert data['name'] == 'AFT Tasks'
        assert data['short_name'] == 'AFT'
        assert data['display'] == 'standalone'
        assert data['start_url'] == '/'
        icon_sizes = {icon['sizes'] for icon in data['icons']}
        assert {'192x192', '512x512'}.issubset(icon_sizes)

    def test_manifest_reflects_custom_app_name(self, api_client, authenticated_session):
        """Manifest name/short_name update immediately after a custom name is set."""
        set_response = authenticated_session.put(
            f'{api_client}/api/branding/app-name',
            json={'name': 'AFT - Work'},
        )
        assert set_response.status_code == 200, set_response.text

        response = requests.get(f'{api_client}/manifest.webmanifest')
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'AFT - Work'
        assert data['short_name'] == 'AFT - Work'[:12]

        _reset_app_name(api_client, authenticated_session)

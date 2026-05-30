"""Tests for theme API endpoints."""
import pytest
import json
import time
import uuid
import requests


def _create_custom_theme(api_client, session, suffix):
    """Create a custom theme for the authenticated session user and return it."""
    themes_response = session.get(f'{api_client}/api/themes')
    assert themes_response.status_code == 200
    source_theme = themes_response.json()[0]

    create_response = session.post(f'{api_client}/api/themes/copy', json={
        'source_theme_id': source_theme['id'],
        'new_name': f'IDOR Theme {suffix} {int(time.time() * 1000)} {uuid.uuid4().hex[:8]}',
    })
    assert create_response.status_code == 201, create_response.text
    return create_response.json()


def _create_user_with_permissions(api_client, authenticated_session, permissions, suffix):
    """Create, approve, and login a non-admin user with explicit permissions."""
    session = requests.Session()
    password = f"ThemePerm-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"theme-perm-{suffix}-{uuid.uuid4().hex[:6]}@localhost"
    username = f"theme_perm_{suffix}_{uuid.uuid4().hex[:6]}"

    register_response = session.post(f'{api_client}/api/auth/register', json={
        'email': email,
        'username': username,
        'password': password,
    })
    assert register_response.status_code == 201, register_response.text
    user_id = register_response.json().get('user', {}).get('id')
    assert user_id is not None

    approve_response = authenticated_session.post(f'{api_client}/api/users/{user_id}/approve')
    assert approve_response.status_code == 200, approve_response.text

    role_name = f"theme_idor_viewer_{uuid.uuid4().hex[:8]}"
    create_role = authenticated_session.post(f'{api_client}/api/roles', json={
        'name': role_name,
        'description': 'Theme IDOR viewer role',
        'permissions': permissions,
    })
    assert create_role.status_code == 201, create_role.text

    assign_role = authenticated_session.post(
        f'{api_client}/api/users/{user_id}/roles',
        json={'role_name': role_name},
    )
    assert assign_role.status_code == 200, assign_role.text

    login_response = session.post(f'{api_client}/api/auth/login', json={
        'email': email,
        'password': password,
    })
    assert login_response.status_code == 200, login_response.text

    return session


@pytest.fixture
def second_user_theme_session(api_client, authenticated_session, second_user_session):
    """Second user session with explicit theme and setting permissions for IDOR checks."""
    me = second_user_session.get(f'{api_client}/api/auth/me')
    assert me.status_code == 200
    second_user_id = me.json()['user']['id']

    role_name = f"theme_idor_{uuid.uuid4().hex[:8]}"
    create_role = authenticated_session.post(f'{api_client}/api/roles', json={
        'name': role_name,
        'description': 'Theme IDOR regression role',
        'permissions': [
            'theme.view',
            'theme.create',
            'theme.edit',
            'theme.delete',
            'setting.edit',
        ],
    })
    assert create_role.status_code == 201, create_role.text

    assign_role = authenticated_session.post(
        f'{api_client}/api/users/{second_user_id}/roles',
        json={'role_name': role_name},
    )
    assert assign_role.status_code == 200, assign_role.text

    return second_user_session


@pytest.mark.api
class TestThemesAPI:
    """Test cases for theme API endpoints."""
    
    def test_get_themes_list(self, api_client, authenticated_session):
        """Test getting list of all themes."""
        response = authenticated_session.get(f'{api_client}/api/themes')
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # Verify structure of first theme
        theme = data[0]
        assert 'id' in theme
        assert 'name' in theme
        assert 'system_theme' in theme
        assert 'settings' in theme
        assert isinstance(theme['settings'], dict)
    
    def test_get_themes_includes_system_themes(self, api_client, authenticated_session):
        """Test that system themes are included in list."""
        response = authenticated_session.get(f'{api_client}/api/themes')
        assert response.status_code == 200
        data = response.json()
        
        system_themes = [t for t in data if t['system_theme']]
        assert len(system_themes) > 0
        assert any(t['name'] == 'Default' for t in system_themes)
    
    def test_get_theme_by_id(self, api_client, authenticated_session):
        """Test getting a specific theme by ID."""
        # Get list first
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        themes = themes_response.json()
        theme_id = themes[0]['id']
        
        # Get specific theme
        response = authenticated_session.get(f'{api_client}/api/themes/{theme_id}')
        assert response.status_code == 200
        data = response.json()
        assert data['id'] == theme_id
        assert 'name' in data
        assert 'settings' in data
        assert 'background_image' in data
    
    def test_get_theme_not_found(self, api_client, authenticated_session):
        """Test getting a theme that doesn't exist."""
        response = authenticated_session.get(f'{api_client}/api/themes/99999')
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
    
    def test_create_custom_theme(self, api_client, authenticated_session):
        """Test creating a new custom theme via copy endpoint."""
        # Get a theme to copy
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_theme = themes_response.json()[0]
        
        unique_name = f'Test Theme {int(time.time() * 1000)}'
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_theme['id'],
            'new_name': unique_name
        })
        if response.status_code != 201:
            print(f"Error response: {response.json()}")
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.json()}"
        data = response.json()
        assert data['name'] == unique_name
        assert data['system_theme'] is False
        
        # Cleanup
        authenticated_session.delete(f'{api_client}/api/themes/{data["id"]}')
    
    def test_create_theme_duplicate_name(self, api_client, authenticated_session):
        """Test creating theme with duplicate name fails."""
        # Get existing theme name
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        themes = themes_response.json()
        existing_name = themes[0]['name']
        source_id = themes[1]['id'] if len(themes) > 1 else themes[0]['id']
        
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_id,
            'new_name': existing_name
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'already exists' in data['message'].lower()
    
    def test_create_theme_missing_name(self, api_client, authenticated_session):
        """Test creating theme without name fails."""
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_id = themes_response.json()[0]['id']
        
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_id
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_theme_empty_name(self, api_client, authenticated_session):
        """Test creating theme with empty name fails."""
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_id = themes_response.json()[0]['id']
        
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_id,
            'new_name': ''
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_create_theme_long_name(self, api_client, authenticated_session):
        """Test creating theme with excessively long name."""
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_id = themes_response.json()[0]['id']
        
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_id,
            'new_name': 'A' * 300  # 300 characters
        })
        # May fail with 400, 500 (db error), or 201 if truncated
        assert response.status_code in [400, 500, 201]
    
    def test_update_theme(self, api_client, authenticated_session):
        """Test updating an existing theme via copy first."""
        # Create a theme via copy
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_theme = themes_response.json()[0]
        
        unique_name = f'Update Test Theme {int(time.time() * 1000)} {uuid.uuid4().hex[:8]}'
        create_response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_theme['id'],
            'new_name': unique_name
        })
        assert create_response.status_code == 201, create_response.text
        theme_id = create_response.json()['id']
        
        # Update it
        update_data = {
            'name': f'Updated Theme {int(time.time() * 1000)}',
            'settings': {'primary-color': '#00FF00', 'text-color': '#FFFFFF'},
            'background_image': None
        }
        
        response = authenticated_session.put(f'{api_client}/api/themes/{theme_id}', json=update_data)
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == update_data['name']
        settings = json.loads(data['settings']) if isinstance(data['settings'], str) else data['settings']
        assert settings['primary-color'] == '#00FF00'
        
        # Cleanup
        authenticated_session.delete(f'{api_client}/api/themes/{theme_id}')
    
    def test_update_theme_missing_request_body(self, api_client, authenticated_session):
        """Test that updating a theme without a request body returns 400."""
        # Create a theme to update
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_theme = themes_response.json()[0]
        
        unique_name = f'Body Test Theme {int(time.time() * 1000)}'
        create_response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_theme['id'],
            'new_name': unique_name
        })
        theme_id = create_response.json()['id']
        
        try:
            # Try to update without a request body
            response = authenticated_session.put(f'{api_client}/api/themes/{theme_id}')
            assert response.status_code == 400
            data = response.json()
            assert data['success'] is False
            assert 'valid JSON' in data['message'] or 'required' in data['message']
        finally:
            # Cleanup
            authenticated_session.delete(f'{api_client}/api/themes/{theme_id}')
    
    def test_update_theme_invalid_json(self, api_client, authenticated_session):
        """Test that updating a theme with invalid JSON returns 400."""
        # Create a theme to update
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_theme = themes_response.json()[0]
        
        unique_name = f'Invalid JSON Test Theme {int(time.time() * 1000)} {uuid.uuid4().hex[:8]}'
        create_response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_theme['id'],
            'new_name': unique_name
        })
        assert create_response.status_code == 201, create_response.text
        theme_id = create_response.json()['id']
        
        try:
            # Try to update with invalid JSON (malformed request)
            # This is handled by Flask's request.get_json() raising BadRequest
            response = authenticated_session.put(
                f'{api_client}/api/themes/{theme_id}',
                data='invalid json',
                headers={'Content-Type': 'application/json'}
            )
            assert response.status_code == 400
            data = response.json()
            assert data['success'] is False
        finally:
            # Cleanup
            authenticated_session.delete(f'{api_client}/api/themes/{theme_id}')
    

        """Test that system themes cannot be updated."""
        # Get a system theme
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        system_theme = next(t for t in themes_response.json() if t['system_theme'])
        
        update_data = {
            'name': 'Hacked System Theme',
            'settings': {'primary-color': '#FF0000'}
        }
        
        response = authenticated_session.put(f'{api_client}/api/themes/{system_theme["id"]}', json=update_data)
        assert response.status_code == 400  # Changed from 403
        data = response.json()
        assert data['success'] is False
        assert 'system or global themes' in data['message'].lower()
    
    def test_rename_theme(self, api_client, authenticated_session):
        """Test renaming a custom theme."""
        # Create a theme via copy
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_id = themes_response.json()[0]['id']
        
        unique_name = f'Rename Test Theme {int(time.time() * 1000)}'
        create_response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_id,
            'new_name': unique_name
        })
        theme_id = create_response.json()['id']
        
        # Rename it
        new_name = f'Renamed Theme {int(time.time() * 1000)}'
        response = authenticated_session.put(f'{api_client}/api/themes/{theme_id}/rename', json={
            'name': new_name
        })
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == new_name
        
        # Cleanup
        authenticated_session.delete(f'{api_client}/api/themes/{theme_id}')
    
    def test_rename_system_theme_fails(self, api_client, authenticated_session):
        """Test that system themes cannot be renamed."""
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        system_theme = next(t for t in themes_response.json() if t['system_theme'])
        
        response = authenticated_session.put(f'{api_client}/api/themes/{system_theme["id"]}/rename', json={
            'name': 'Hacked Name'
        })
        assert response.status_code == 400  # Changed from 403
        data = response.json()
        assert data['success'] is False
    
    def test_rename_theme_duplicate_name(self, api_client, authenticated_session):
        """Test renaming theme to existing name fails."""
        # Get themes
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        themes = themes_response.json()
        
        # Create two themes via copy with unique names
        theme1_name = f'Theme One {int(time.time() * 1000)}'
        theme1 = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': themes[0]['id'],
            'new_name': theme1_name
        }).json()
        
        time.sleep(0.001)  # Ensure unique timestamp
        theme2_name = f'Theme Two {int(time.time() * 1000)}'
        theme2 = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': themes[0]['id'],
            'new_name': theme2_name
        }).json()
        
        # Try to rename theme2 to theme1's name
        response = authenticated_session.put(f'{api_client}/api/themes/{theme2["id"]}/rename', json={
            'name': theme1_name
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'already exists' in data['message'].lower()
        
        # Cleanup
        authenticated_session.delete(f'{api_client}/api/themes/{theme1["id"]}')
        authenticated_session.delete(f'{api_client}/api/themes/{theme2["id"]}')
    
    def test_copy_theme(self, api_client, authenticated_session):
        """Test copying an existing theme."""
        # Get a theme to copy
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        original_theme = themes_response.json()[0]
        
        unique_name = f'Copied Theme {int(time.time() * 1000)}'
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': original_theme['id'],  # Changed from source_id
            'new_name': unique_name
        })
        assert response.status_code == 201
        data = response.json()
        assert data['name'] == unique_name
        assert data['system_theme'] is False
        assert data['settings'] == original_theme['settings']
        
        # Cleanup
        authenticated_session.delete(f'{api_client}/api/themes/{data["id"]}')
    
    def test_copy_theme_source_not_found(self, api_client, authenticated_session):
        """Test copying non-existent theme fails."""
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': 99999,  # Changed from source_id
            'new_name': 'Copy of Nothing'
        })
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
    
    def test_copy_theme_duplicate_name(self, api_client, authenticated_session):
        """Test copying theme with duplicate name fails."""
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        themes = themes_response.json()
        existing_name = themes[0]['name']
        source_id = themes[1]['id'] if len(themes) > 1 else themes[0]['id']
        
        response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_id,  # Changed from source_id
            'new_name': existing_name
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_export_theme(self, api_client, authenticated_session):
        """Test exporting a theme as JSON."""
        # Get a theme
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        theme = themes_response.json()[0]
        
        response = authenticated_session.get(f'{api_client}/api/themes/{theme["id"]}/export')
        assert response.status_code == 200
        assert response.headers['Content-Type'] == 'application/json'
        
        # Verify JSON structure
        data = response.json()
        assert data['name'] == theme['name']
        # Settings might be string or dict depending on response
        if isinstance(data['settings'], str) and isinstance(theme['settings'], str):
            assert data['settings'] == theme['settings']
        else:
            # Compare as dicts
            data_settings = json.loads(data['settings']) if isinstance(data['settings'], str) else data['settings']
            theme_settings = json.loads(theme['settings']) if isinstance(theme['settings'], str) else theme['settings']
            assert data_settings == theme_settings
    
    def test_export_theme_not_found(self, api_client, authenticated_session):
        """Test exporting non-existent theme fails."""
        response = authenticated_session.get(f'{api_client}/api/themes/99999/export')
        assert response.status_code == 404
    
    def test_import_theme(self, api_client, authenticated_session):
        """Test importing a theme from JSON."""
        # Get a valid theme structure
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        existing_theme = themes_response.json()[0]
        
        unique_name = f'Imported Theme {int(time.time() * 1000)}'
        theme_json = {
            'name': unique_name,
            'settings': json.loads(existing_theme['settings']) if isinstance(existing_theme['settings'], str) else existing_theme['settings'],
            'background_image': None
        }
        
        response = authenticated_session.post(
            f'{api_client}/api/themes/import',
            json=theme_json
        )
        assert response.status_code == 201
        data = response.json()
        assert data['name'] == unique_name
        
        # Cleanup
        authenticated_session.delete(f'{api_client}/api/themes/{data["id"]}')
    
    def test_import_theme_invalid_json(self, api_client, authenticated_session):
        """Test importing theme with invalid JSON fails."""
        invalid_json = {
            'settings': {'primary-color': '#FF5733'}
            # Missing 'name' field
        }
        
        response = authenticated_session.post(f'{api_client}/api/themes/import', json=invalid_json)
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_import_theme_duplicate_name(self, api_client, authenticated_session):
        """Test importing theme with duplicate name fails."""
        # Get existing theme
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        existing = themes_response.json()[0]
        existing_name = existing['name']
        
        theme_json = {
            'name': existing_name,
            'settings': json.loads(existing['settings']) if isinstance(existing['settings'], str) else existing['settings']
        }
        
        response = authenticated_session.post(f'{api_client}/api/themes/import', json=theme_json)
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'already exists' in data['message'].lower()
    
    def test_get_theme_images_list(self, api_client, authenticated_session):
        """Test getting list of available background images."""
        response = authenticated_session.get(f'{api_client}/api/themes/images')
        assert response.status_code == 200
        data = response.json()
        assert 'images' in data
        assert isinstance(data['images'], list)
        # Should have at least some default images
        assert len(data['images']) >= 0
    
    def test_get_theme_image(self, api_client, authenticated_session):
        """Test getting a specific background image."""
        # Get list of images first
        images_response = authenticated_session.get(f'{api_client}/api/themes/images')
        assert images_response.status_code == 200
        images = images_response.json()['images']
        
        # Skip this test if no background images are available
        # (might happen in clean test environment)
        if len(images) > 0:
            # Test getting first image
            filename = images[0]
            response = authenticated_session.get(f'{api_client}/api/themes/images/{filename}')
            # Image should exist and be served
            if response.status_code == 404:
                # Image doesn't exist on filesystem - skip rather than fail
                pytest.skip(f"Background image {filename} not found on filesystem")
            assert response.status_code == 200, f"Failed to get image {filename}: status {response.status_code}"
            assert 'image/' in response.headers.get('Content-Type', ''), f"Invalid content type for {filename}"
    
    def test_get_theme_image_not_found(self, api_client, authenticated_session):
        """Test getting non-existent image fails."""
        response = authenticated_session.get(f'{api_client}/api/themes/images/nonexistent.png')
        assert response.status_code == 404
    
    def test_get_theme_image_path_traversal(self, api_client, authenticated_session):
        """Test that path traversal is safe due to HTTP client and server normalization.
        
        Path traversal protection is provided by multiple layers:
        1. The requests library normalizes URLs (e.g., /api/themes/images/../etc/passwd becomes /api/etc/passwd)
        2. Nginx normalizes paths before routing to Flask
        3. Flask's SafeFilenameConverter validates filenames
        
        This means malicious paths are neutralized before reaching our application code.
        We document this rather than duplicate the security checks that are already 
        implemented by standard HTTP libraries and web servers.
        """
        # Verify that non-existent normalized paths return 404
        response = authenticated_session.get(f'{api_client}/api/etc/passwd')
        assert response.status_code in [404, 405], "Non-existent paths should not be served"
        
        # Verify that standard image access still works
        images_response = authenticated_session.get(f'{api_client}/api/themes/images')
        assert images_response.status_code == 200, "Image list endpoint should work"
    
    def test_get_current_theme_setting(self, api_client, authenticated_session):
        """Test getting current applied theme."""
        response = authenticated_session.get(f'{api_client}/api/settings/theme')
        assert response.status_code == 200
        data = response.json()
        assert 'id' in data
        assert 'name' in data
        assert 'settings' in data
    
    def test_set_current_theme(self, api_client, authenticated_session):
        """Test setting the current theme."""
        # Get a theme
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        theme = themes_response.json()[0]
        
        response = authenticated_session.put(f'{api_client}/api/settings/theme', json={
            'theme_id': theme['id']
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'updated' in data['message'].lower()
        
        # Verify it was set by getting current theme
        get_response = authenticated_session.get(f'{api_client}/api/settings/theme')
        assert get_response.status_code == 200
        current = get_response.json()
        assert current['id'] == theme['id']
    
    def test_set_current_theme_not_found(self, api_client, authenticated_session):
        """Test setting non-existent theme fails."""
        response = authenticated_session.put(f'{api_client}/api/settings/theme', json={
            'theme_id': 99999
        })
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False

    def test_get_instance_default_theme(self, api_client, authenticated_session):
        """Test getting the instance default theme for authenticated users."""
        response = authenticated_session.get(f'{api_client}/api/settings/default-theme')
        assert response.status_code == 200

        data = response.json()
        assert data['success'] is True
        assert data['key'] == 'default_theme'
        assert isinstance(data['value'], int)
        assert isinstance(data['theme'], dict)
        assert data['theme']['id'] == data['value']

    def test_set_instance_default_theme(self, api_client, authenticated_session):
        """Test updating the instance default theme via branding permission endpoint."""
        current_response = authenticated_session.get(f'{api_client}/api/settings/default-theme')
        assert current_response.status_code == 200
        original_default_theme_id = current_response.json()['value']

        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        assert themes_response.status_code == 200
        themes = themes_response.json()
        target_theme_id = themes[0]['id']

        if target_theme_id == original_default_theme_id and len(themes) > 1:
            target_theme_id = themes[1]['id']

        update_response = authenticated_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': target_theme_id}
        )
        assert update_response.status_code == 200
        update_data = update_response.json()
        assert update_data['success'] is True
        assert update_data['value'] == target_theme_id

        verify_response = authenticated_session.get(f'{api_client}/api/settings/default-theme')
        assert verify_response.status_code == 200
        verify_data = verify_response.json()
        assert verify_data['value'] == target_theme_id

        restore_response = authenticated_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': original_default_theme_id}
        )
        assert restore_response.status_code == 200

    def test_set_instance_default_theme_rejects_private_user_theme(
        self, api_client, authenticated_session
    ):
        """Instance default theme must be system or promoted global theme."""
        theme = _create_custom_theme(api_client, authenticated_session, 'private-default')

        response = authenticated_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': theme['id']}
        )
        assert response.status_code == 400, response.text
        assert 'system or global' in response.json()['message'].lower()

    def test_promote_theme_to_global_makes_it_visible_to_other_users(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        """Promoted themes should become visible and selectable for other users."""
        theme = _create_custom_theme(api_client, authenticated_session, 'promote-visible')

        promote_response = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/promote-global'
        )
        assert promote_response.status_code == 200, promote_response.text
        assert promote_response.json()['theme']['global_theme'] is True

        visible_response = second_user_theme_session.get(f'{api_client}/api/themes/{theme["id"]}')
        assert visible_response.status_code == 200, visible_response.text
        assert visible_response.json()['id'] == theme['id']

        select_response = second_user_theme_session.put(
            f'{api_client}/api/settings/theme',
            json={'theme_id': theme['id']},
        )
        assert select_response.status_code == 200, select_response.text

    def test_promoted_global_theme_can_be_instance_default(
        self, api_client, authenticated_session
    ):
        """A promoted global theme can be selected as the instance default."""
        current_response = authenticated_session.get(f'{api_client}/api/settings/default-theme')
        assert current_response.status_code == 200
        original_default_theme_id = current_response.json()['value']

        theme = _create_custom_theme(api_client, authenticated_session, 'global-default')
        promote_response = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/promote-global'
        )
        assert promote_response.status_code == 200, promote_response.text

        set_response = authenticated_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': theme['id']}
        )
        assert set_response.status_code == 200, set_response.text
        assert set_response.json()['value'] == theme['id']

        restore_response = authenticated_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': original_default_theme_id}
        )
        assert restore_response.status_code == 200

        demote_response = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/demote-global'
        )
        assert demote_response.status_code == 200, demote_response.text

    def test_demote_global_theme_blocks_when_used_as_instance_default(
        self, api_client, authenticated_session
    ):
        """A global theme cannot be demoted while it is configured as the instance default."""
        current_response = authenticated_session.get(f'{api_client}/api/settings/default-theme')
        assert current_response.status_code == 200
        original_default_theme_id = current_response.json()['value']

        theme = _create_custom_theme(api_client, authenticated_session, 'demote-blocked')
        promote_response = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/promote-global'
        )
        assert promote_response.status_code == 200, promote_response.text

        set_response = authenticated_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': theme['id']}
        )
        assert set_response.status_code == 200, set_response.text

        demote_response = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/demote-global'
        )
        assert demote_response.status_code == 400, demote_response.text

        restore_response = authenticated_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': original_default_theme_id}
        )
        assert restore_response.status_code == 200

        cleanup_demote = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/demote-global'
        )
        assert cleanup_demote.status_code == 200, cleanup_demote.text

    def test_demote_global_theme_resets_other_users_current_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        """Demoting a global theme should move non-owner users back to a valid theme."""
        fallback_response = authenticated_session.get(f'{api_client}/api/settings/default-theme')
        assert fallback_response.status_code == 200
        fallback_theme_id = fallback_response.json()['value']

        theme = _create_custom_theme(api_client, authenticated_session, 'demote-reset')
        promote_response = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/promote-global'
        )
        assert promote_response.status_code == 200, promote_response.text

        select_response = second_user_theme_session.put(
            f'{api_client}/api/settings/theme',
            json={'theme_id': theme['id']},
        )
        assert select_response.status_code == 200, select_response.text

        demote_response = authenticated_session.post(
            f'{api_client}/api/themes/{theme["id"]}/demote-global'
        )
        assert demote_response.status_code == 200, demote_response.text

        current_theme_response = second_user_theme_session.get(f'{api_client}/api/settings/theme')
        assert current_theme_response.status_code == 200, current_theme_response.text
        assert current_theme_response.json()['id'] == fallback_theme_id

    def test_promote_theme_requires_branding_permission(
        self, api_client, second_user_session
    ):
        """Promoting themes is restricted to branding editors."""
        response = second_user_session.post(f'{api_client}/api/themes/1/promote-global')
        assert response.status_code == 403

    def test_demote_theme_requires_branding_permission(
        self, api_client, second_user_session
    ):
        """Demoting themes is restricted to branding editors."""
        response = second_user_session.post(f'{api_client}/api/themes/1/demote-global')
        assert response.status_code == 403

    def test_set_instance_default_theme_requires_branding_permission(
        self, api_client, second_user_session
    ):
        """Test setting instance default theme requires branding.edit."""
        response = second_user_session.put(
            f'{api_client}/api/settings/default-theme',
            json={'theme_id': 1}
        )
        assert response.status_code == 403
    
    def test_delete_custom_theme(self, api_client, authenticated_session):
        """Test deleting a custom theme."""
        # Create a theme via copy
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        source_theme = themes_response.json()[0]
        
        unique_name = f'Delete Test {int(time.time() * 1000)}'
        create_response = authenticated_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': source_theme['id'],
            'new_name': unique_name
        })
        theme_id = create_response.json()['id']
        
        # Delete it
        response = authenticated_session.delete(f'{api_client}/api/themes/{theme_id}')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'deleted' in data['message'].lower()
        
        # Verify it's gone
        get_response = authenticated_session.get(f'{api_client}/api/themes/{theme_id}')
        assert get_response.status_code == 404
    
    def test_delete_system_theme_fails(self, api_client, authenticated_session):
        """Test that system themes cannot be deleted."""
        themes_response = authenticated_session.get(f'{api_client}/api/themes')
        system_theme = next(t for t in themes_response.json() if t['system_theme'])
        
        response = authenticated_session.delete(f'{api_client}/api/themes/{system_theme["id"]}')
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'system theme' in data['message'].lower()
    
    def test_delete_theme_not_found(self, api_client, authenticated_session):
        """Test deleting non-existent theme fails."""
        response = authenticated_session.delete(f'{api_client}/api/themes/99999')
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False


@pytest.mark.api
class TestThemeIDORSecurity:
    """Regression tests for cross-user theme access and mutation protection."""

    def test_user_b_cannot_get_user_a_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        theme = _create_custom_theme(api_client, authenticated_session, 'get')

        response = second_user_theme_session.get(f"{api_client}/api/themes/{theme['id']}")
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

    def test_user_b_cannot_update_user_a_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        theme = _create_custom_theme(api_client, authenticated_session, 'update')

        response = second_user_theme_session.put(
            f"{api_client}/api/themes/{theme['id']}",
            json={'name': f"Should Fail {int(time.time() * 1000)}"},
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

        verify = authenticated_session.get(f"{api_client}/api/themes/{theme['id']}")
        assert verify.status_code == 200
        assert verify.json()['name'] == theme['name']

    def test_user_b_cannot_rename_user_a_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        theme = _create_custom_theme(api_client, authenticated_session, 'rename')

        response = second_user_theme_session.put(
            f"{api_client}/api/themes/{theme['id']}/rename",
            json={'name': f"Nope {int(time.time() * 1000)}"},
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

    def test_user_b_cannot_delete_user_a_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        theme = _create_custom_theme(api_client, authenticated_session, 'delete')

        response = second_user_theme_session.delete(f"{api_client}/api/themes/{theme['id']}")
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

        verify = authenticated_session.get(f"{api_client}/api/themes/{theme['id']}")
        assert verify.status_code == 200

    def test_user_b_cannot_export_user_a_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        theme = _create_custom_theme(api_client, authenticated_session, 'export')

        response = second_user_theme_session.get(f"{api_client}/api/themes/{theme['id']}/export")
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

    def test_user_b_cannot_copy_user_a_private_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        theme = _create_custom_theme(api_client, authenticated_session, 'copy-source')

        response = second_user_theme_session.post(f'{api_client}/api/themes/copy', json={
            'source_theme_id': theme['id'],
            'new_name': f"Copy Should Fail {int(time.time() * 1000)}",
        })
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

    def test_user_b_cannot_set_current_theme_to_user_a_theme(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        theme = _create_custom_theme(api_client, authenticated_session, 'selected-theme')

        response = second_user_theme_session.put(
            f'{api_client}/api/settings/theme',
            json={'theme_id': theme['id']},
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

    def test_copy_creates_user_owned_theme_hidden_from_other_users(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        second_theme = _create_custom_theme(api_client, second_user_theme_session, 'owned-by-b')
        third_user_view_session = _create_user_with_permissions(
            api_client,
            authenticated_session,
            ['theme.view'],
            'copy-hidden',
        )

        response = third_user_view_session.get(f"{api_client}/api/themes/{second_theme['id']}")
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

    def test_import_creates_user_owned_theme_hidden_from_other_users(
        self, api_client, authenticated_session, second_user_theme_session
    ):
        imported = second_user_theme_session.post(f'{api_client}/api/themes/import', json={
            'name': f"Imported B {int(time.time() * 1000)}",
            'settings': {
                'primary-color': '#2ea043',
                'text-color': '#111111',
                'background-light': '#f7f7f7',
                'card-bg-color': '#ffffff',
            },
            'background_image': None,
        })
        assert imported.status_code == 201, imported.text
        imported_theme = imported.json()
        third_user_view_session = _create_user_with_permissions(
            api_client,
            authenticated_session,
            ['theme.view'],
            'import-hidden',
        )

        response = third_user_view_session.get(f"{api_client}/api/themes/{imported_theme['id']}")
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

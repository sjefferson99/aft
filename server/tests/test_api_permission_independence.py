"""Permission independence tests.

These tests verify that a user with exactly one assigned permission can perform
at least one representative API action for that permission without needing
additional permissions.
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
import requests

from permissions import PERMISSION_DEFINITIONS


def _normalize_api_base_url(api_client):
    """Normalize API base URL from fixture for consistent URL joining."""
    return api_client.rstrip("/")


def _render(value, context):
    """Render template values using context placeholders."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.format(**context)
    if isinstance(value, dict):
        return {k: _render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, context) for v in value]
    return value


def _request(session, api_base_url, method, path, payload=None):
    """Perform an API request with optional JSON body."""
    return session.request(method, f"{api_base_url}{path}", json=payload, timeout=10)


def _create_board_context(admin_session, api_base_url, suffix):
    """Create board resources used by permission tests."""
    board_resp = admin_session.post(
        f"{api_base_url}/api/boards",
        json={"name": f"Permission Board {suffix}", "description": "permission test board"},
        timeout=10,
    )
    assert board_resp.status_code == 201, board_resp.text
    board_id = board_resp.json()["board"]["id"]

    col_resp = admin_session.post(
        f"{api_base_url}/api/boards/{board_id}/columns",
        json={"name": f"Source Column {suffix}"},
        timeout=10,
    )
    assert col_resp.status_code == 201, col_resp.text
    column_id = col_resp.json()["column"]["id"]

    col2_resp = admin_session.post(
        f"{api_base_url}/api/boards/{board_id}/columns",
        json={"name": f"Target Column {suffix}"},
        timeout=10,
    )
    assert col2_resp.status_code == 201, col2_resp.text
    second_column_id = col2_resp.json()["column"]["id"]

    card_resp = admin_session.post(
        f"{api_base_url}/api/columns/{column_id}/cards",
        json={"title": f"Card {suffix}", "description": "permission test card"},
        timeout=10,
    )
    assert card_resp.status_code == 201, card_resp.text
    card_id = card_resp.json()["card"]["id"]

    unscheduled_card_resp = admin_session.post(
        f"{api_base_url}/api/columns/{column_id}/cards",
        json={"title": f"Unscheduled {suffix}", "description": "for schedule.create"},
        timeout=10,
    )
    assert unscheduled_card_resp.status_code == 201, unscheduled_card_resp.text
    unscheduled_card_id = unscheduled_card_resp.json()["card"]["id"]

    scheduled_source_resp = admin_session.post(
        f"{api_base_url}/api/columns/{column_id}/cards",
        json={"title": f"Scheduled Source {suffix}", "description": "for schedule.edit/delete/view"},
        timeout=10,
    )
    assert scheduled_source_resp.status_code == 201, scheduled_source_resp.text
    scheduled_source_card_id = scheduled_source_resp.json()["card"]["id"]

    future_iso = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    schedule_resp = admin_session.post(
        f"{api_base_url}/api/schedules",
        json={
            "card_id": scheduled_source_card_id,
            "run_every": 1,
            "unit": "day",
            "start_datetime": future_iso,
            "schedule_enabled": True,
            "allow_duplicates": False,
        },
        timeout=10,
    )
    assert schedule_resp.status_code == 201, schedule_resp.text
    schedule_id = schedule_resp.json()["schedule"]["id"]

    theme_resp = admin_session.post(
        f"{api_base_url}/api/themes/import",
        json={
            "name": f"Perm Theme {suffix}",
            "settings": {
                "primary-color": "#1f6feb",
                "text-color": "#111111",
                "background-light": "#f7f7f7",
                "card-bg-color": "#ffffff",
            },
        },
        timeout=10,
    )
    assert theme_resp.status_code == 201, theme_resp.text
    theme_id = theme_resp.json()["id"]

    return {
        "suffix": suffix,
        "board_id": board_id,
        "column_id": column_id,
        "second_column_id": second_column_id,
        "card_id": card_id,
        "unscheduled_card_id": unscheduled_card_id,
        "schedule_id": schedule_id,
        "theme_id": theme_id,
        "future_iso": future_iso,
    }


def _create_permission_user(admin_session, api_base_url, suffix):
    """Register, approve, and login a user for permission testing."""
    email = f"perm-{suffix}@test.local"
    username = f"perm_{suffix}"
    password = f"PermUser-{uuid.uuid4().hex}-Aa1!"

    register_resp = requests.post(
        f"{api_base_url}/api/auth/register",
        json={"email": email, "username": username, "password": password},
        timeout=10,
    )
    assert register_resp.status_code == 201, register_resp.text

    register_data = register_resp.json()
    user_id = register_data.get("user", {}).get("id")

    if not user_id:
        pending_resp = admin_session.get(f"{api_base_url}/api/users/pending", timeout=10)
        assert pending_resp.status_code == 200, pending_resp.text
        pending_users = pending_resp.json().get("users", [])
        matching = [u for u in pending_users if u.get("email") == email]
        assert matching, f"Registered user {email} not found in pending list"
        user_id = matching[0]["id"]

    approve_resp = admin_session.post(f"{api_base_url}/api/users/{user_id}/approve", timeout=10)
    assert approve_resp.status_code == 200, approve_resp.text

    user_session = requests.Session()
    login_resp = user_session.post(
        f"{api_base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    assert login_resp.status_code == 200, login_resp.text

    return user_id, user_session


def _create_single_permission_role(admin_session, api_base_url, permission, suffix):
    """Create a custom role containing only one permission."""
    role_name = f"perm_{permission.replace('.', '_')}_{suffix}"
    role_resp = admin_session.post(
        f"{api_base_url}/api/roles",
        json={
            "name": role_name,
            "description": f"Single permission role for {permission}",
            "permissions": [permission],
        },
        timeout=10,
    )
    assert role_resp.status_code == 201, role_resp.text
    return role_name


def _assign_role(admin_session, api_base_url, user_id, role_name, board_id=None):
    """Assign a role to a user globally or for a specific board."""
    payload = {"role_name": role_name}
    if board_id is not None:
        payload["board_id"] = board_id

    assign_resp = admin_session.post(
        f"{api_base_url}/api/users/{user_id}/roles",
        json=payload,
        timeout=10,
    )
    assert assign_resp.status_code == 200, assign_resp.text


PERMISSION_CASES = [
    {
        "permission": "system.admin",
        "scope": "global",
        "method": "GET",
        "path": "/api/roles",
        "json": None,
        "expected": {200},
    },
    {"permission": "monitoring.system", "scope": "global", "method": "GET", "path": "/api/broadcast-status", "json": None, "expected": {200}},
    {"permission": "admin.database", "scope": "global", "method": "GET", "path": "/api/database/backups/list", "json": None, "expected": {200}},
    {"permission": "branding.edit", "scope": "global", "method": "DELETE", "path": "/api/branding/logo", "json": None, "expected": {200}},
    {"permission": "user.manage", "scope": "global", "method": "GET", "path": "/api/users", "json": None, "expected": {200}},
    {"permission": "user.role", "scope": "global", "method": "GET", "path": "/api/roles", "json": None, "expected": {200}},
    {"permission": "role.manage", "scope": "global", "method": "GET", "path": "/api/roles", "json": None, "expected": {200}},
    {"permission": "board.create", "scope": "global", "method": "POST", "path": "/api/boards", "json": {"name": "Created by board.create {suffix}"}, "expected": {201}},
    {"permission": "board.view", "scope": "board", "method": "GET", "path": "/api/boards", "json": None, "expected": {200}},
    {"permission": "board.edit", "scope": "board", "method": "PATCH", "path": "/api/boards/{board_id}", "json": {"name": "Edited Board {suffix}"}, "expected": {200}},
    {"permission": "board.delete", "scope": "board", "method": "DELETE", "path": "/api/boards/{board_id}", "json": None, "expected": {200}},
    {"permission": "column.create", "scope": "board", "method": "POST", "path": "/api/boards/{board_id}/columns", "json": {"name": "Created Column {suffix}"}, "expected": {201}},
    {"permission": "column.update", "scope": "board", "method": "PATCH", "path": "/api/columns/{column_id}", "json": {"name": "Updated Column {suffix}"}, "expected": {200}},
    {"permission": "column.delete", "scope": "board", "method": "DELETE", "path": "/api/columns/{column_id}", "json": None, "expected": {200}},
    {"permission": "card.create", "scope": "board", "method": "POST", "path": "/api/columns/{column_id}/cards", "json": {"title": "Created Card {suffix}", "description": "created by card.create"}, "expected": {201}},
    {"permission": "card.view", "scope": "board", "method": "GET", "path": "/api/cards/{card_id}", "json": None, "expected": {200}},
    {"permission": "card.edit", "scope": "board", "method": "POST", "path": "/api/columns/{column_id}/cards/move", "json": {"target_column_id": "{second_column_id}", "position": "bottom"}, "expected": {200}},
    {"permission": "card.update", "scope": "board", "method": "PATCH", "path": "/api/cards/{card_id}", "json": {"title": "Updated Card {suffix}"}, "expected": {200}},
    {"permission": "card.delete", "scope": "board", "method": "DELETE", "path": "/api/cards/{card_id}", "json": None, "expected": {200}},
    {"permission": "card.archive", "scope": "board", "method": "PATCH", "path": "/api/cards/{card_id}/archive", "json": None, "expected": {200}},
    {"permission": "schedule.create", "scope": "board", "method": "POST", "path": "/api/schedules", "json": {"card_id": "{unscheduled_card_id}", "run_every": 1, "unit": "day", "start_datetime": "{future_iso}"}, "expected": {201}},
    {"permission": "schedule.view", "scope": "board", "method": "GET", "path": "/api/schedules/{schedule_id}", "json": None, "expected": {200}},
    {"permission": "schedule.edit", "scope": "board", "method": "PUT", "path": "/api/schedules/{schedule_id}", "json": {"run_every": 2}, "expected": {200}},
    {"permission": "schedule.delete", "scope": "board", "method": "DELETE", "path": "/api/schedules/{schedule_id}", "json": None, "expected": {200}},
    {"permission": "setting.view", "scope": "global", "method": "GET", "path": "/api/settings/schema", "json": None, "expected": {200}},
    {"permission": "setting.edit", "scope": "global", "method": "PUT", "path": "/api/settings/default_board", "json": {"value": None}, "expected": {200}},
    {"permission": "theme.create", "scope": "global", "method": "POST", "path": "/api/themes/import", "json": {"name": "Created Theme {suffix}", "settings": {"primary-color": "#2ea043", "text-color": "#111111", "background-light": "#f7f7f7", "card-bg-color": "#ffffff"}}, "expected": {201}},
    {"permission": "theme.view", "scope": "global", "method": "GET", "path": "/api/themes", "json": None, "expected": {200}},
    # With ownership scoping, a user with theme.edit/theme.delete but without ownership
    # of admin-created context themes should get fail-closed "not found".
    {"permission": "theme.edit", "scope": "global", "method": "PUT", "path": "/api/themes/{theme_id}", "json": {"name": "Edited Theme {suffix}"}, "expected": {404}},
    {"permission": "theme.delete", "scope": "global", "method": "DELETE", "path": "/api/themes/{theme_id}", "json": None, "expected": {404}},
]


@pytest.mark.parametrize("case", PERMISSION_CASES, ids=lambda c: c["permission"])
def test_single_permission_is_sufficient_for_representative_action(
    authenticated_session, api_client, case
):
    """A user with one permission should be able to perform that permission's action."""
    api_base_url = _normalize_api_base_url(api_client)
    suffix = uuid.uuid4().hex[:8]
    context = _create_board_context(authenticated_session, api_base_url, suffix)

    user_id, user_session = _create_permission_user(authenticated_session, api_base_url, suffix)
    role_name = _create_single_permission_role(
        authenticated_session, api_base_url, case["permission"], suffix
    )

    board_scope_id = context["board_id"] if case["scope"] == "board" else None
    _assign_role(authenticated_session, api_base_url, user_id, role_name, board_id=board_scope_id)

    path = _render(case["path"], context)
    payload = _render(case.get("json"), context)

    response = _request(user_session, api_base_url, case["method"], path, payload)

    assert response.status_code != 401, (
        f"Unexpected unauthenticated response for permission '{case['permission']}' "
        f"on {case['method']} {path}: {response.text}"
    )
    assert response.status_code != 403, (
        f"Permission '{case['permission']}' was not sufficient for {case['method']} {path}. "
        f"Response: {response.text}"
    )
    assert response.status_code in case["expected"], (
        f"Unexpected status for permission '{case['permission']}' on {case['method']} {path}. "
        f"Expected {sorted(case['expected'])}, got {response.status_code}. Body: {response.text}"
    )


def test_boards_endpoint_returns_helpful_403_for_user_with_no_board_access(
    authenticated_session, api_client,
):
    """A user with no board roles/perms should get a clear 403 from GET /api/boards."""
    api_base_url = _normalize_api_base_url(api_client)
    suffix = uuid.uuid4().hex[:8]
    user_id, user_session = _create_permission_user(authenticated_session, api_base_url, suffix)

    # Remove default board_creator role so we can test the "no board access" scenario
    roles_response = authenticated_session.get(f"{api_base_url}/api/roles", timeout=10)
    assert roles_response.status_code == 200
    board_creator_role = next(
        (r for r in roles_response.json().get("roles", []) if r["name"] == "board_creator"),
        None
    )
    if board_creator_role:
        remove_response = authenticated_session.delete(
            f"{api_base_url}/api/users/{user_id}/roles/{board_creator_role['id']}",
            timeout=10
        )
        assert remove_response.status_code == 200, remove_response.text

    response = _request(user_session, api_base_url, "GET", "/api/boards")

    assert response.status_code == 403, response.text
    data = response.json()
    assert data.get("success") is False
    assert data.get("error") == "boards_access_denied"
    assert "do not have access to any existing boards" in data.get("message", "")
    assert data.get("details", {}).get("can_create_board") is False
    assert data.get("details", {}).get("has_board_access") is False


def test_permission_model_gaps_are_explicit():
    """Keep unbound permission definitions explicit until API coverage exists."""
    exercised_permissions = {case["permission"] for case in PERMISSION_CASES}
    defined_permissions = set(PERMISSION_DEFINITIONS)
    actual_unbound = defined_permissions - exercised_permissions

    assert actual_unbound == set(), (
        "Every permission definition should now have API coverage. "
        f"Found unbound permissions: {sorted(actual_unbound)}"
    )

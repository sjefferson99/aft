"""Check real responses against the published Swagger spec (#660).

API clients generate tools from /api/apispec.json and validate responses
against it, so a field documented as a plain string that comes back null breaks
them. These tests fetch sparse records (no dates, no description, a user who
has never signed in) and validate each response against its documented schema.
"""
import copy
import uuid

import jsonschema
import pytest
import requests


def _to_json_schema(node):
    """Convert a Swagger 2.0 schema to JSON Schema, honouring x-nullable."""
    if isinstance(node, list):
        return [_to_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {k: _to_json_schema(v) for k, v in node.items() if k not in ("example", "x-nullable")}
    if node.get("x-nullable") and "type" in out:
        types = out["type"] if isinstance(out["type"], list) else [out["type"]]
        out["type"] = types + ["null"]
        if "enum" in out:
            out["enum"] = list(out["enum"]) + [None]
    return out


@pytest.fixture
def spec(api_client):
    response = requests.get(f"{api_client}/api/apispec.json", timeout=10)
    assert response.status_code == 200
    return response.json()


def _assert_matches_spec(spec, path, method, response, status=200):
    assert response.status_code == status, response.text
    schema = copy.deepcopy(spec["paths"][path][method]["responses"][str(status)]["schema"])
    # Shared models are $refs to #/definitions, so carry those along.
    schema["definitions"] = copy.deepcopy(spec.get("definitions", {}))
    validator = jsonschema.Draft7Validator(_to_json_schema(schema))
    errors = sorted(
        f"{'/'.join(map(str, error.absolute_path))}: {error.message}"
        for error in validator.iter_errors(response.json())
    )
    assert not errors, f"{method.upper()} {path} does not match the spec:\n" + "\n".join(errors)


@pytest.mark.api
class TestSpecConformance:
    """Responses with null fields must match the documented schemas."""

    def test_spec_uses_swagger2_nullable_only(self, spec):
        """The spec is Swagger 2.0, so null is marked with x-nullable, never OpenAPI 3's nullable."""
        found = []

        def walk(node, path):
            if isinstance(node, dict):
                if "nullable" in node:
                    found.append(path)
                for key, value in node.items():
                    walk(value, f"{path}/{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}/{index}")

        walk(spec["paths"], "")
        assert not found, f"Use x-nullable instead of nullable at: {found}"

    def test_card_without_dates_matches_spec(self, api_client, authenticated_session, sample_column, spec):
        create = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "No dates", "description": None},
        )
        _assert_matches_spec(spec, "/api/columns/{column_id}/cards", "post", create, status=201)
        card_id = create.json()["card"]["id"]

        fetched = authenticated_session.get(f"{api_client}/api/cards/{card_id}")
        _assert_matches_spec(spec, "/api/cards/{card_id}", "get", fetched)
        assert fetched.json()["card"]["start_date"] is None
        assert fetched.json()["card"]["end_date"] is None

        patched = authenticated_session.patch(f"{api_client}/api/cards/{card_id}", json={"title": "Renamed"})
        _assert_matches_spec(spec, "/api/cards/{card_id}", "patch", patched)

        column_cards = authenticated_session.get(f"{api_client}/api/columns/{sample_column['id']}/cards")
        _assert_matches_spec(spec, "/api/columns/{column_id}/cards", "get", column_cards)

        board_cards = authenticated_session.get(f"{api_client}/api/boards/{sample_column['board_id']}/cards")
        _assert_matches_spec(spec, "/api/boards/{board_id}/cards", "get", board_cards)

    def test_board_without_description_matches_spec(self, api_client, authenticated_session, spec):
        create = authenticated_session.post(f"{api_client}/api/boards", json={"name": "No description"})
        assert create.status_code == 201
        board_id = create.json()["board"]["id"]
        try:
            patched = authenticated_session.patch(
                f"{api_client}/api/boards/{board_id}", json={"name": "Still no description"}
            )
            _assert_matches_spec(spec, "/api/boards/{board_id}", "patch", patched)
        finally:
            authenticated_session.delete(f"{api_client}/api/boards/{board_id}")

    def test_users_never_signed_in_match_spec(self, api_client, authenticated_session, spec):
        suffix = uuid.uuid4().hex[:8]
        email = f"spec-check-{suffix}@localhost"
        register = requests.post(f"{api_client}/api/auth/register", json={
            "email": email,
            "username": f"spec-check-{suffix}",
            "password": f"SpecCheck-{suffix}-Aa1!",
        })
        assert register.status_code == 201
        pending = authenticated_session.get(f"{api_client}/api/users/pending")
        user_id = next(u["id"] for u in pending.json()["users"] if u["email"] == email)
        try:
            users = authenticated_session.get(f"{api_client}/api/users")
            _assert_matches_spec(spec, "/api/users", "get", users)
            listed = next(u for u in users.json()["users"] if u["id"] == user_id)
            assert listed["last_login_at"] is None
        finally:
            authenticated_session.post(f"{api_client}/api/users/{user_id}/reject")

    def test_current_user_matches_spec(self, api_client, authenticated_session, spec):
        me = authenticated_session.get(f"{api_client}/api/auth/me")
        _assert_matches_spec(spec, "/api/auth/me", "get", me)

    def test_backup_config_matches_spec(self, api_client, authenticated_session, spec):
        config = authenticated_session.get(f"{api_client}/api/settings/backup/config")
        _assert_matches_spec(spec, "/api/settings/backup/config", "get", config)

    def test_api_tokens_match_spec(self, api_client, authenticated_session, spec):
        """A new token has no expiry and has never been used, so both dates are null."""
        suffix = uuid.uuid4().hex[:8]
        email = f"spec-token-{suffix}@localhost"
        password = f"SpecToken-{suffix}-Aa1!"
        register = requests.post(f"{api_client}/api/auth/register", json={
            "email": email,
            "username": f"spec-token-{suffix}",
            "password": password,
        })
        assert register.status_code == 201
        pending = authenticated_session.get(f"{api_client}/api/users/pending")
        user_id = next(u["id"] for u in pending.json()["users"] if u["email"] == email)
        approve = authenticated_session.post(f"{api_client}/api/users/{user_id}/approve")
        assert approve.status_code == 200, approve.text
        auth = (email, password)

        created = requests.post(f"{api_client}/api/auth/tokens", json={"name": "Spec"}, auth=auth)
        _assert_matches_spec(spec, "/api/auth/tokens", "post", created, status=201)
        assert created.json()["api_token"]["expires_at"] is None

        listed = requests.get(f"{api_client}/api/auth/tokens", auth=auth)
        _assert_matches_spec(spec, "/api/auth/tokens", "get", listed)
        assert listed.json()["tokens"][0]["last_used_at"] is None

        admin_listed = authenticated_session.get(f"{api_client}/api/users/{user_id}/tokens")
        _assert_matches_spec(spec, "/api/users/{user_id}/tokens", "get", admin_listed)

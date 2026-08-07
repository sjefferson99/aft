"""Tests for public board read-only API endpoints."""

import requests
import pytest
import time


@pytest.mark.api
class TestPublicBoardsAPI:
    """Test cases for anonymous public board access."""

    def test_toggle_public_board_generates_slug(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Updating a board to public should generate a shareable slug."""
        response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert response.status_code == 200, response.text

        data = response.json()
        assert data["success"] is True
        assert data["board"]["is_public"] is True
        assert isinstance(data["board"]["public_slug"], str)
        assert len(data["board"]["public_slug"]) >= 8

    def test_public_board_anonymous_read_returns_redacted_payload(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Anonymous callers can read public boards with redacted fields only."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Public Card", "description": "Visible without auth"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        checklist_response = authenticated_session.post(
            f"{api_client}/api/cards/{card_id}/checklist-items",
            json={"name": "Checklist task", "checked": False},
        )
        assert checklist_response.status_code == 201

        comment_response = authenticated_session.post(
            f"{api_client}/api/cards/{card_id}/comments",
            json={"comment": "Public comment content"},
        )
        assert comment_response.status_code == 201

        make_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert make_public_response.status_code == 200, make_public_response.text
        slug = make_public_response.json()["board"]["public_slug"]

        public_response = requests.get(f"{api_client}/api/public/boards/{slug}")
        assert public_response.status_code == 200
        assert public_response.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
        assert "no-store" in (public_response.headers.get("Cache-Control") or "")

        data = public_response.json()
        assert data["success"] is True

        board = data["board"]
        assert board["id"] == sample_board["id"]
        assert board["is_public"] is True
        assert board["public_slug"] == slug
        assert isinstance(board.get("default_theme"), dict)
        assert isinstance(board["default_theme"].get("id"), int)
        assert isinstance(board["default_theme"].get("settings"), dict)
        assert "owner" not in board
        assert "assignee_filter_users" not in board
        assert "can_edit" not in board

        column = board["columns"][0]
        card = column["cards"][0]
        assert card["title"] == "Public Card"
        assert "assigned_to" not in card
        assert "assigned_to_id" not in card
        assert "schedule" not in card
        assert "scheduled" not in card

        assert len(card["checklist_items"]) == 1
        assert card["checklist_items"][0]["name"] == "Checklist task"

        # Public board list endpoint returns comment_count only, not comment
        # bodies -- see docs/PERFORMANCE_board_updates.md item 1.5. Full
        # comment content is available via the public single-card endpoint.
        assert "comments" not in card
        assert card["comment_count"] == 1

    def test_public_board_headers_are_present_via_nginx_http_and_https(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Public board crawler/cache headers should be preserved through nginx in both protocols."""
        make_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert make_public_response.status_code == 200, make_public_response.text
        slug = make_public_response.json()["board"]["public_slug"]

        http_response = requests.get(f"{api_client}/api/public/boards/{slug}")
        assert http_response.status_code == 200
        assert http_response.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
        assert "no-store" in (http_response.headers.get("Cache-Control") or "")

        https_url = f"https://localhost/api/public/boards/{slug}"
        https_response = requests.get(https_url, verify=False)
        assert https_response.status_code == 200
        assert https_response.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
        assert "no-store" in (https_response.headers.get("Cache-Control") or "")

    def test_public_board_uses_configured_instance_default_theme(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Public board payload should resolve theme from instance default setting."""
        current_default_response = authenticated_session.get(f"{api_client}/api/settings/default-theme")
        assert current_default_response.status_code == 200
        original_default_theme_id = current_default_response.json()["value"]

        themes_response = authenticated_session.get(f"{api_client}/api/themes")
        assert themes_response.status_code == 200
        source_theme = themes_response.json()[0]

        promoted_theme_response = authenticated_session.post(
            f"{api_client}/api/themes/copy",
            json={
                "source_theme_id": source_theme["id"],
                "new_name": f"Public Board Global Theme {int(time.time() * 1000)}",
            },
        )
        assert promoted_theme_response.status_code == 201, promoted_theme_response.text
        target_theme_id = promoted_theme_response.json()["id"]

        promote_response = authenticated_session.post(
            f"{api_client}/api/themes/{target_theme_id}/promote-global"
        )
        assert promote_response.status_code == 200, promote_response.text

        set_default_response = authenticated_session.put(
            f"{api_client}/api/settings/default-theme",
            json={"theme_id": target_theme_id},
        )
        assert set_default_response.status_code == 200

        make_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert make_public_response.status_code == 200
        slug = make_public_response.json()["board"]["public_slug"]

        public_response = requests.get(f"{api_client}/api/public/boards/{slug}")
        assert public_response.status_code == 200
        payload = public_response.json()
        assert payload["board"]["default_theme"]["id"] == target_theme_id

        restore_response = authenticated_session.put(
            f"{api_client}/api/settings/default-theme",
            json={"theme_id": original_default_theme_id},
        )
        assert restore_response.status_code == 200

        demote_response = authenticated_session.post(
            f"{api_client}/api/themes/{target_theme_id}/demote-global"
        )
        assert demote_response.status_code == 200, demote_response.text

    def test_private_or_revoked_public_board_returns_not_found(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Anonymous callers should get not-found for private or revoked boards."""
        private_response = requests.get(f"{api_client}/api/public/boards/doesnotexist")
        assert private_response.status_code == 404

        make_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert make_public_response.status_code == 200, make_public_response.text
        slug = make_public_response.json()["board"]["public_slug"]

        revoke_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": False},
        )
        assert revoke_response.status_code == 200
        assert revoke_response.json()["board"]["public_slug"] == slug

        after_revoke_response = requests.get(f"{api_client}/api/public/boards/{slug}")
        assert after_revoke_response.status_code == 404

    def test_reenable_public_board_reuses_existing_slug(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Public slug should remain stable across private/public toggles until explicitly rotated."""
        first_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert first_public_response.status_code == 200, first_public_response.text
        slug = first_public_response.json()["board"]["public_slug"]

        private_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": False},
        )
        assert private_response.status_code == 200, private_response.text
        assert private_response.json()["board"]["public_slug"] == slug

        second_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert second_public_response.status_code == 200, second_public_response.text
        assert second_public_response.json()["board"]["public_slug"] == slug

    def test_rotate_public_link_replaces_slug_and_invalidates_old_link(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Explicit rotation should issue a new slug and invalidate the prior public URL."""
        public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert public_response.status_code == 200, public_response.text
        old_slug = public_response.json()["board"]["public_slug"]

        rotate_response = authenticated_session.post(
            f"{api_client}/api/boards/{sample_board['id']}/public-link/rotate",
            json={},
        )
        assert rotate_response.status_code == 200, rotate_response.text

        rotate_data = rotate_response.json()
        assert rotate_data["success"] is True
        assert rotate_data["previous_public_slug"] == old_slug
        new_slug = rotate_data["board"]["public_slug"]
        assert isinstance(new_slug, str)
        assert new_slug != old_slug

        old_link_response = requests.get(f"{api_client}/api/public/boards/{old_slug}")
        assert old_link_response.status_code == 404

        new_link_response = requests.get(f"{api_client}/api/public/boards/{new_slug}")
        assert new_link_response.status_code == 200

    def test_rotate_public_link_requires_public_board(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Cannot rotate a link for a board that is currently private."""
        rotate_response = authenticated_session.post(
            f"{api_client}/api/boards/{sample_board['id']}/public-link/rotate",
            json={},
        )
        assert rotate_response.status_code == 400

    def test_anonymous_rotate_public_link_is_denied(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Anonymous callers cannot rotate links even if board is public."""
        make_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert make_public_response.status_code == 200, make_public_response.text

        rotate_response = requests.post(
            f"{api_client}/api/boards/{sample_board['id']}/public-link/rotate",
            json={},
        )
        assert rotate_response.status_code == 401

    def test_anonymous_write_requests_are_denied_even_for_public_boards(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Public visibility must not allow any anonymous write endpoint access."""
        make_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert make_public_response.status_code == 200, make_public_response.text

        create_column_response = requests.post(
            f"{api_client}/api/boards/{sample_board['id']}/columns",
            json={"name": "Anonymous Column"},
        )
        assert create_column_response.status_code == 401

        patch_board_response = requests.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"name": "Anonymous Update"},
        )
        assert patch_board_response.status_code == 401

        delete_board_response = requests.delete(f"{api_client}/api/boards/{sample_board['id']}")
        assert delete_board_response.status_code == 401

@pytest.mark.api
class TestPublicCardAPI:
    """Test cases for the public single-card read endpoint."""

    def _make_board_public(self, api_client, authenticated_session, board_id):
        """Helper: make a board public and return its slug."""
        response = authenticated_session.patch(
            f"{api_client}/api/boards/{board_id}",
            json={"is_public": True},
        )
        assert response.status_code == 200, response.text
        return response.json()["board"]["public_slug"]

    def test_anonymous_can_read_public_card(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Anonymous users can fetch a single card from a public board."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Test Card", "description": "Visible to public"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/{card_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        card = data["card"]
        assert card["id"] == card_id
        assert card["title"] == "Test Card"
        assert card["description"] == "Visible to public"
        assert "column_id" in card
        assert "checklist_items" in card
        assert "comments" in card

    def test_public_card_excludes_sensitive_fields(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Public card endpoint should not expose assignee, scheduled, or schedule fields."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Sensitive Card"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/{card_id}")
        assert response.status_code == 200

        card = response.json()["card"]
        assert "assigned_to" not in card
        assert "assigned_to_id" not in card
        assert "schedule" not in card
        assert "scheduled" not in card

    def test_public_card_includes_checklist_and_comments(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Public card endpoint should include checklist items and comments."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Card with items"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        authenticated_session.post(
            f"{api_client}/api/cards/{card_id}/checklist-items",
            json={"name": "Do something", "checked": False},
        )
        authenticated_session.post(
            f"{api_client}/api/cards/{card_id}/comments",
            json={"comment": "A public comment"},
        )

        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/{card_id}")
        assert response.status_code == 200

        card = response.json()["card"]
        assert len(card["checklist_items"]) == 1
        assert card["checklist_items"][0]["name"] == "Do something"
        assert len(card["comments"]) == 1
        assert card["comments"][0]["comment"] == "A public comment"
        assert "user_id" not in card["comments"][0]
        assert "author" not in card["comments"][0]

    def test_public_card_not_found_for_private_board(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Card on a private board should not be accessible via public endpoint."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Private Card"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        # Make public to get the slug, then revoke public access
        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])
        authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": False},
        )

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/{card_id}")
        assert response.status_code == 404

    def test_public_card_not_found_for_invalid_slug(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Public card endpoint should return 404 for an invalid board slug."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Card"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        response = requests.get(f"{api_client}/api/public/boards/invalidslug/cards/{card_id}")
        assert response.status_code == 404

    def test_public_card_not_found_for_nonexistent_card(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Public card endpoint returns 404 for a card ID that does not exist on the board."""
        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/999999")
        assert response.status_code == 404

    def test_public_card_response_headers(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Public card endpoint should include correct crawler/cache headers."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Header Test Card"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/{card_id}")
        assert response.status_code == 200
        assert response.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
        assert "no-store" in (response.headers.get("Cache-Control") or "")

    def test_anonymous_can_read_done_public_card(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Done cards should be readable from the public single-card endpoint."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Done Public Card"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        mark_done_response = authenticated_session.patch(
            f"{api_client}/api/cards/{card_id}/done",
            json={"done": True},
        )
        assert mark_done_response.status_code == 200, mark_done_response.text

        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/{card_id}")
        assert response.status_code == 200
        card = response.json()["card"]
        assert card["id"] == card_id
        assert card["done"] is True

    def test_anonymous_can_read_archived_public_card(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Archived cards should be readable from the public single-card endpoint."""
        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Archived Public Card"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        archive_response = authenticated_session.patch(
            f"{api_client}/api/cards/{card_id}/archive"
        )
        assert archive_response.status_code == 200, archive_response.text

        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        response = requests.get(f"{api_client}/api/public/boards/{slug}/cards/{card_id}")
        assert response.status_code == 200
        card = response.json()["card"]
        assert card["id"] == card_id
        assert card["archived"] is True

    def test_anonymous_cannot_write_cards_on_public_board(
        self,
        api_client,
        authenticated_session,
        sample_board,
        sample_column,
    ):
        """Public board visibility must not allow anonymous card creation or updates."""
        slug = self._make_board_public(api_client, authenticated_session, sample_board["id"])

        create_response = requests.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Anonymous Card"},
        )
        assert create_response.status_code == 401

        card_response = authenticated_session.post(
            f"{api_client}/api/columns/{sample_column['id']}/cards",
            json={"title": "Existing Card"},
        )
        assert card_response.status_code == 201
        card_id = card_response.json()["card"]["id"]

        patch_response = requests.patch(
            f"{api_client}/api/cards/{card_id}",
            json={"title": "Modified by anon"},
        )
        assert patch_response.status_code == 401

        delete_response = requests.delete(f"{api_client}/api/cards/{card_id}")
        assert delete_response.status_code == 401



@pytest.mark.api
class TestPublicBoardThrottling:
    """Burst-traffic throttling tests — run last to avoid polluting the rate-limit window."""

    def test_public_board_read_throttling_engages_under_burst_traffic(
        self,
        api_client,
        authenticated_session,
        sample_board,
    ):
        """Burst traffic should trigger public-read throttling (app or proxy layer)."""
        make_public_response = authenticated_session.patch(
            f"{api_client}/api/boards/{sample_board['id']}",
            json={"is_public": True},
        )
        assert make_public_response.status_code == 200, make_public_response.text
        slug = make_public_response.json()["board"]["public_slug"]

        statuses = []
        for _ in range(95):
            response = requests.get(f"{api_client}/api/public/boards/{slug}", timeout=5)
            statuses.append(response.status_code)
        # Proxy limiting may return 503 by default; app limiter returns 429.
        throttled_statuses = [status for status in statuses if status in (429, 503)]
        assert throttled_statuses, f"Expected throttling under burst traffic, got statuses: {set(statuses)}"

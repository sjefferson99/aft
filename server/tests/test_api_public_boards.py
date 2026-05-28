"""Tests for public board read-only API endpoints."""

import requests
import pytest


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

        assert len(card["comments"]) == 1
        assert card["comments"][0]["comment"] == "Public comment content"
        assert "user_id" not in card["comments"][0]
        assert "author" not in card["comments"][0]

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

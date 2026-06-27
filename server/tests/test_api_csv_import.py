"""Tests for CSV board import endpoints.

Covers: template download, preview, new-board import, existing-board import
(duplicate and overwrite strategies), validation errors, and permission checks.
"""
import io
import pytest
import requests


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

MINIMAL_CSV = (
    "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
    "Card One,Todo,,,,,\r\n"
    "Card Two,In Progress,,,,,\r\n"
)

CHECKLIST_CSV = (
    "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
    "Task A,Todo,,Buy groceries,Milk|Eggs[done]|Bread,,\r\n"
)

DATES_CSV = (
    "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
    "Dated Card,Todo,,,,2026-07-01,2026-07-07\r\n"
)

BAD_DATE_CSV = (
    "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
    "Bad Date Card,Todo,,,,01/07/2026,\r\n"
)

MISSING_TITLE_CSV = (
    "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
    ",Todo,,,,,\r\n"
)

MISSING_REQUIRED_HEADER_CSV = (
    "title,assignee,description\r\n"
    "Card One,alice,some desc\r\n"
)

UNKNOWN_ASSIGNEE_CSV = (
    "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
    "Card One,Todo,ghost-user-xyz,,,\r\n"
)


def _csv_file(content: str, filename: str = "import.csv"):
    return ("file", (filename, content.encode("utf-8"), "text/csv"))


def _make_board(api_client, session, name="CSV Test Board"):
    resp = session.post(f"{api_client}/api/boards", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["board"]


def _board_columns(api_client, session, board_id):
    resp = session.get(f"{api_client}/api/boards/{board_id}/columns")
    assert resp.status_code == 200, resp.text
    return resp.json()["columns"]


def _column_cards(api_client, session, col_id):
    resp = session.get(f"{api_client}/api/columns/{col_id}/cards")
    assert resp.status_code == 200, resp.text
    return resp.json()["cards"]


def _board_cards_flat(api_client, session, board_id):
    """Return flat list of all cards from the board cards response (includes assigned_to_id)."""
    resp = session.get(f"{api_client}/api/boards/{board_id}/cards")
    assert resp.status_code == 200, resp.text
    return [card for col in resp.json()["board"]["columns"] for card in col["cards"]]


def _card_detail(api_client, session, card_id):
    """Return full card detail (includes start_date, end_date)."""
    resp = session.get(f"{api_client}/api/cards/{card_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["card"]


# ---------------------------------------------------------------------------
# Template download
# ---------------------------------------------------------------------------

@pytest.mark.api
class TestCSVTemplateDownload:
    """Tests for GET /api/boards/import/csv-template."""

    def test_template_download_returns_csv(self, api_client):
        """Template endpoint returns a CSV file without requiring auth."""
        resp = requests.get(f"{api_client}/api/boards/import/csv-template")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")

    def test_template_contains_required_headers(self, api_client):
        resp = requests.get(f"{api_client}/api/boards/import/csv-template")
        assert resp.status_code == 200
        first_line = resp.text.splitlines()[0]
        for col in ("title", "column", "assignee", "description",
                    "checklist_items", "start_date", "end_date"):
            assert col in first_line.lower()

    def test_template_has_example_rows(self, api_client):
        resp = requests.get(f"{api_client}/api/boards/import/csv-template")
        lines = [l for l in resp.text.splitlines() if l.strip()]
        assert len(lines) >= 3, "Template should have header + at least 2 example rows"

    def test_template_dates_are_iso_format(self, api_client):
        """Example dates in template must be YYYY-MM-DD to avoid spreadsheet reformatting."""
        import re
        resp = requests.get(f"{api_client}/api/boards/import/csv-template")
        # Find all quoted date-like strings and check format
        date_pattern = re.compile(r'"(\d{4}-\d{2}-\d{2})"')
        dates = date_pattern.findall(resp.text)
        assert len(dates) >= 2, "Template should contain at least 2 ISO date examples"


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------

@pytest.mark.api
class TestCSVImportPreview:
    """Tests for POST /api/boards/import/preview."""

    def test_preview_requires_auth(self, api_client):
        resp = requests.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(MINIMAL_CSV)],
            data={"target_board_id": "1"},
        )
        assert resp.status_code == 401

    def test_preview_missing_file(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            data={"target_board_id": str(board["id"])},
        )
        assert resp.status_code == 400

    def test_preview_missing_board_id(self, api_client, authenticated_session):
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(MINIMAL_CSV)],
        )
        assert resp.status_code == 400

    def test_preview_board_not_found(self, api_client, authenticated_session):
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(MINIMAL_CSV)],
            data={"target_board_id": "999999"},
        )
        assert resp.status_code == 404

    def test_preview_invalid_csv_surfaces_errors(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(BAD_DATE_CSV)],
            data={"target_board_id": str(board["id"])},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert isinstance(data.get("errors"), list)
        assert len(data["errors"]) > 0
        assert any("YYYY-MM-DD" in e for e in data["errors"])

    def test_preview_missing_required_header_surfaces_errors(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(MISSING_REQUIRED_HEADER_CSV)],
            data={"target_board_id": str(board["id"])},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert any("column" in e.lower() for e in data.get("errors", []))

    def test_preview_all_new_cards_on_empty_board(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(MINIMAL_CSV)],
            data={"target_board_id": str(board["id"])},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["matched_cards"] == []
        assert len(data["new_cards"]) == 2
        assert len(data["new_columns"]) == 2

    def test_preview_detects_matched_cards(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        # seed one card that will match
        col_resp = authenticated_session.post(
            f"{api_client}/api/boards/{board['id']}/columns",
            json={"name": "Todo"},
        )
        assert col_resp.status_code == 201
        col_id = col_resp.json()["column"]["id"]
        card_resp = authenticated_session.post(
            f"{api_client}/api/columns/{col_id}/cards",
            json={"title": "Card One"},
        )
        assert card_resp.status_code == 201

        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(MINIMAL_CSV)],
            data={"target_board_id": str(board["id"])},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["matched_cards"]) == 1
        assert data["matched_cards"][0]["title"] == "Card One"
        assert len(data["new_cards"]) == 1

    def test_preview_unknown_assignee_returns_warning(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[_csv_file(UNKNOWN_ASSIGNEE_CSV)],
            data={"target_board_id": str(board["id"])},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert any("ghost-user-xyz" in w for w in data.get("warnings", []))

    def test_preview_rejects_non_csv(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import/preview",
            files=[("file", ("board.json", b"{}", "application/json"))],
            data={"target_board_id": str(board["id"])},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# New board CSV import
# ---------------------------------------------------------------------------

@pytest.mark.api
class TestCSVImportNewBoard:
    """Tests for POST /api/boards/import with CSV — new board mode."""

    def _import_csv(self, api_client, session, csv_content, board_name="CSV Board"):
        return session.post(
            f"{api_client}/api/boards/import",
            files=[_csv_file(csv_content)],
            data={"target_mode": "new_board", "board_name": board_name},
        )

    def test_new_board_import_success(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, MINIMAL_CSV, "My CSV Board")
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["board"]["name"] == "My CSV Board"

    def test_new_board_columns_created(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, MINIMAL_CSV)
        board_id = resp.json()["board"]["id"]
        columns = _board_columns(api_client, authenticated_session, board_id)
        col_names = {c["name"] for c in columns}
        assert "Todo" in col_names
        assert "In Progress" in col_names

    def test_new_board_cards_created(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, MINIMAL_CSV)
        board_id = resp.json()["board"]["id"]
        columns = _board_columns(api_client, authenticated_session, board_id)
        all_cards = []
        for col in columns:
            all_cards.extend(_column_cards(api_client, authenticated_session, col["id"]))
        titles = {c["title"] for c in all_cards}
        assert "Card One" in titles
        assert "Card Two" in titles

    def test_new_board_checklist_items_created(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, CHECKLIST_CSV)
        board_id = resp.json()["board"]["id"]
        columns = _board_columns(api_client, authenticated_session, board_id)
        all_cards = []
        for col in columns:
            all_cards.extend(_column_cards(api_client, authenticated_session, col["id"]))
        task_a = next((c for c in all_cards if c["title"] == "Task A"), None)
        assert task_a is not None
        chk = task_a.get("checklist_items", [])
        assert len(chk) == 3
        item_names = [i["name"] for i in chk]
        assert "Milk" in item_names
        assert "Eggs" in item_names
        assert "Bread" in item_names
        eggs = next(i for i in chk if i["name"] == "Eggs")
        assert eggs["checked"] is True
        milk = next(i for i in chk if i["name"] == "Milk")
        assert milk["checked"] is False

    def test_new_board_dates_mapped(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, DATES_CSV)
        board_id = resp.json()["board"]["id"]
        flat_cards = _board_cards_flat(api_client, authenticated_session, board_id)
        dated_stub = next((c for c in flat_cards if c["title"] == "Dated Card"), None)
        assert dated_stub is not None
        dated = _card_detail(api_client, authenticated_session, dated_stub["id"])
        assert dated["start_date"] is not None
        assert "2026-07-01" in dated["start_date"]
        assert dated["end_date"] is not None
        assert "2026-07-07" in dated["end_date"]

    def test_new_board_invalid_date_rejected(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, BAD_DATE_CSV)
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert any("YYYY-MM-DD" in e for e in data.get("errors", [data.get("message", "")]))

    def test_new_board_missing_required_header_rejected(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, MISSING_REQUIRED_HEADER_CSV)
        assert resp.status_code == 400

    def test_new_board_missing_title_row_rejected(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, MISSING_TITLE_CSV)
        assert resp.status_code == 400

    def test_new_board_unknown_assignee_imports_without_assignee(self, api_client, authenticated_session):
        resp = self._import_csv(api_client, authenticated_session, UNKNOWN_ASSIGNEE_CSV)
        assert resp.status_code == 201
        data = resp.json()
        assert any("ghost-user-xyz" in w for w in data["import_meta"]["warnings"])
        board_id = data["board"]["id"]
        flat_cards = _board_cards_flat(api_client, authenticated_session, board_id)
        assert len(flat_cards) == 1
        assert flat_cards[0].get("assigned_to") is None

    def test_new_board_known_assignee_is_mapped(self, api_client, authenticated_session):
        csv = (
            "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
            "Card One,Todo,test-admin,,,,\r\n"
        )
        resp = self._import_csv(api_client, authenticated_session, csv)
        assert resp.status_code == 201
        data = resp.json()
        board_id = data["board"]["id"]
        flat_cards = _board_cards_flat(api_client, authenticated_session, board_id)
        assert len(flat_cards) == 1
        assignee = flat_cards[0].get("assigned_to")
        assert assignee is not None
        assert assignee["username"] == "test-admin"

    def test_new_board_name_defaults_to_filename_stem(self, api_client, authenticated_session):
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import",
            files=[_csv_file(MINIMAL_CSV, "my-project.csv")],
            data={"target_mode": "new_board"},
        )
        assert resp.status_code == 201
        name = resp.json()["board"]["name"]
        assert "my-project" in name

    def test_new_board_duplicate_name_gets_suffix(self, api_client, authenticated_session):
        self._import_csv(api_client, authenticated_session, MINIMAL_CSV, "Duplicate CSV Board")
        resp2 = self._import_csv(api_client, authenticated_session, MINIMAL_CSV, "Duplicate CSV Board")
        assert resp2.status_code == 201
        assert resp2.json()["board"]["name"] != "Duplicate CSV Board"

    def test_new_board_requires_auth(self, api_client):
        resp = requests.post(
            f"{api_client}/api/boards/import",
            files=[_csv_file(MINIMAL_CSV)],
            data={"target_mode": "new_board", "board_name": "Unauth"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Existing board CSV import — duplicate strategy
# ---------------------------------------------------------------------------

@pytest.mark.api
class TestCSVImportExistingBoardDuplicate:
    """POST /api/boards/import — existing_board + duplicate strategy."""

    def _import_into(self, api_client, session, board_id, csv_content, strategy="duplicate"):
        return session.post(
            f"{api_client}/api/boards/import",
            files=[_csv_file(csv_content)],
            data={
                "target_mode": "existing_board",
                "target_board_id": str(board_id),
                "conflict_strategy": strategy,
            },
        )

    def test_duplicate_all_new_cards_added(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = self._import_into(api_client, authenticated_session, board["id"], MINIMAL_CSV)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["import_meta"]["created_count"] == 2

    def test_duplicate_matched_cards_get_suffix(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        col_resp = authenticated_session.post(
            f"{api_client}/api/boards/{board['id']}/columns",
            json={"name": "Todo"},
        )
        col_id = col_resp.json()["column"]["id"]
        authenticated_session.post(
            f"{api_client}/api/columns/{col_id}/cards",
            json={"title": "Card One"},
        )

        resp = self._import_into(api_client, authenticated_session, board["id"], MINIMAL_CSV)
        assert resp.status_code == 201
        data = resp.json()
        assert data["import_meta"]["created_count"] >= 2

        cards = _column_cards(api_client, authenticated_session, col_id)
        titles = {c["title"] for c in cards}
        assert "Card One" in titles
        assert any("(2)" in t for t in titles), f"Expected suffixed title, got {titles}"

    def test_duplicate_missing_board_id_rejected(self, api_client, authenticated_session):
        resp = authenticated_session.post(
            f"{api_client}/api/boards/import",
            files=[_csv_file(MINIMAL_CSV)],
            data={"target_mode": "existing_board", "conflict_strategy": "duplicate"},
        )
        assert resp.status_code == 400

    def test_duplicate_board_not_found_rejected(self, api_client, authenticated_session):
        resp = self._import_into(api_client, authenticated_session, 999999, MINIMAL_CSV)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Existing board CSV import — overwrite strategy
# ---------------------------------------------------------------------------

@pytest.mark.api
class TestCSVImportExistingBoardOverwrite:
    """POST /api/boards/import — existing_board + overwrite strategy."""

    def _import_into(self, api_client, session, board_id, csv_content):
        return session.post(
            f"{api_client}/api/boards/import",
            files=[_csv_file(csv_content)],
            data={
                "target_mode": "existing_board",
                "target_board_id": str(board_id),
                "conflict_strategy": "overwrite",
            },
        )

    def test_overwrite_updates_matched_card(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        col_resp = authenticated_session.post(
            f"{api_client}/api/boards/{board['id']}/columns",
            json={"name": "Todo"},
        )
        col_id = col_resp.json()["column"]["id"]
        authenticated_session.post(
            f"{api_client}/api/columns/{col_id}/cards",
            json={"title": "Card One", "description": "original"},
        )

        overwrite_csv = (
            "title,column,assignee,description,checklist_items,start_date,end_date\r\n"
            "Card One,Todo,,updated description,,,,\r\n"
        )
        resp = self._import_into(api_client, authenticated_session, board["id"], overwrite_csv)
        assert resp.status_code == 201, resp.text

        cards = _column_cards(api_client, authenticated_session, col_id)
        card_one = next(c for c in cards if c["title"] == "Card One")
        assert card_one["description"] == "updated description"

    def test_overwrite_does_not_create_duplicate(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        col_resp = authenticated_session.post(
            f"{api_client}/api/boards/{board['id']}/columns",
            json={"name": "Todo"},
        )
        col_id = col_resp.json()["column"]["id"]
        authenticated_session.post(
            f"{api_client}/api/columns/{col_id}/cards",
            json={"title": "Card One"},
        )

        resp = self._import_into(api_client, authenticated_session, board["id"], MINIMAL_CSV)
        assert resp.status_code == 201

        cards = _column_cards(api_client, authenticated_session, col_id)
        matching = [c for c in cards if c["title"] == "Card One"]
        assert len(matching) == 1, f"Expected 1 card named 'Card One', got {len(matching)}"

    def test_overwrite_creates_new_cards_and_columns(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        resp = self._import_into(api_client, authenticated_session, board["id"], MINIMAL_CSV)
        assert resp.status_code == 201
        data = resp.json()
        assert data["import_meta"]["created_count"] == 2
        columns = _board_columns(api_client, authenticated_session, board["id"])
        col_names = {c["name"] for c in columns}
        assert "Todo" in col_names
        assert "In Progress" in col_names

    def test_overwrite_response_includes_updated_count(self, api_client, authenticated_session):
        board = _make_board(api_client, authenticated_session)
        col_resp = authenticated_session.post(
            f"{api_client}/api/boards/{board['id']}/columns",
            json={"name": "Todo"},
        )
        col_id = col_resp.json()["column"]["id"]
        authenticated_session.post(
            f"{api_client}/api/columns/{col_id}/cards",
            json={"title": "Card One"},
        )
        resp = self._import_into(api_client, authenticated_session, board["id"], MINIMAL_CSV)
        assert resp.status_code == 201
        assert resp.json()["import_meta"]["updated_count"] == 1

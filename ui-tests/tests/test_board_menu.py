"""UI tests for the board menu choices (#621): the current value is shown, not just implied."""
import pytest

pytestmark = pytest.mark.ui

STYLE = "#toggle-board-style-menu-item"
VISIBILITY = "#toggle-board-visibility-menu-item"
MOBILE_STYLE = "#mobile-toggle-board-style-menu-item"
MOBILE_VISIBILITY = "#mobile-toggle-board-visibility-menu-item"


def open_board_menu(page, board):
    page.goto(f"/board.html?id={board['id']}")
    page.locator(STYLE).wait_for(state="attached", timeout=8000)
    page.wait_for_function(
        f"() => document.querySelector('{VISIBILITY}')?.style.display === ''", timeout=8000
    )
    page.locator(".settings-dropdown .icon-link").click()
    page.locator(STYLE).wait_for(state="visible", timeout=5000)


def pressed(page, selector):
    return page.locator(f'{selector} button[aria-pressed="true"]').all_inner_texts()


def board_style(api_session, ui_base_url, board):
    response = api_session.get(f"{ui_base_url}/api/boards/{board['id']}/settings/working-style")
    assert response.status_code == 200, response.text
    body = response.json()
    return body.get("value") or body.get("working_style")


def test_board_style_shows_current_value_and_saves_a_change(
    logged_in_page, api_session, board, ui_base_url
):
    page = logged_in_page
    open_board_menu(page, board)
    before = pressed(page, STYLE)
    assert len(before) == 1

    other = "Agile" if before == ["Kanban"] else "Kanban"
    page.locator(STYLE).get_by_role("button", name=other).click()

    page.wait_for_function(
        f"""() => document.querySelector('{STYLE} button[aria-pressed="true"]').textContent === '{other}'""",
        timeout=5000,
    )
    assert board_style(api_session, ui_base_url, board) == other.lower()


def test_clicking_the_current_value_changes_nothing(logged_in_page, board):
    page = logged_in_page
    open_board_menu(page, board)
    current = pressed(page, STYLE)[0]

    requests = []
    page.on(
        "request",
        lambda request: requests.append(request.url) if request.method == "PUT" else None,
    )
    page.locator(STYLE).get_by_role("button", name=current).click()
    page.wait_for_timeout(300)

    assert requests == []
    assert pressed(page, STYLE) == [current]


def test_failed_style_change_shows_an_error_and_keeps_the_value(logged_in_page, board):
    page = logged_in_page
    page.context.route(
        "**/settings/working-style",
        lambda route: route.fulfill(status=500, json={"success": False, "message": "Nope"})
        if route.request.method == "PUT" else route.fallback(),
    )
    open_board_menu(page, board)
    current = pressed(page, STYLE)[0]
    other = "Agile" if current == "Kanban" else "Kanban"

    page.locator(STYLE).get_by_role("button", name=other).click()

    toast = page.locator(".error-toast")
    toast.wait_for(state="visible", timeout=5000)
    assert "board style" in toast.inner_text()
    assert pressed(page, STYLE) == [current]


def test_cancelling_the_visibility_dialog_keeps_the_board_private(logged_in_page, board):
    page = logged_in_page
    open_board_menu(page, board)
    assert pressed(page, VISIBILITY) == ["Private"]

    page.locator(VISIBILITY).get_by_role("button", name="Public").click()
    modal = page.locator("#board-visibility-confirm-modal")
    modal.wait_for(state="visible", timeout=5000)
    modal.get_by_role("button", name="Cancel").click()
    modal.wait_for(state="detached", timeout=5000)

    assert pressed(page, VISIBILITY) == ["Private"]
    assert page.locator("#copy-public-link-menu-item").evaluate("el => el.style.display") == "none"


def test_public_board_groups_link_actions_under_visibility(logged_in_page, api_session, board, ui_base_url):
    response = api_session.patch(f"{ui_base_url}/api/boards/{board['id']}", json={"is_public": True})
    assert response.status_code == 200, response.text

    page = logged_in_page
    open_board_menu(page, board)
    assert pressed(page, VISIBILITY) == ["Public"]

    ids = page.locator("#settings-dropdown-menu > *").evaluate_all(
        "items => items.filter(item => item.style.display !== 'none').map(item => item.id).filter(Boolean)"
    )
    start = ids.index("toggle-board-visibility-menu-item")
    assert ids[start + 1:start + 4] == [
        "copy-public-link-menu-item", "rotate-public-link-menu-item", "copy-embed-code-menu-item",
    ]

    page.locator(VISIBILITY).get_by_role("button", name="Private").click()
    modal = page.locator("#board-visibility-confirm-modal")
    modal.wait_for(state="visible", timeout=5000)
    modal.get_by_role("button", name="Make Private").click()
    page.wait_for_function(
        f"""() => document.querySelector('{VISIBILITY} button[aria-pressed="true"]').textContent === 'Private'""",
        timeout=5000,
    )


def test_mobile_drawer_shows_the_same_choices(logged_in_page, api_session, board, ui_base_url):
    page = logged_in_page
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(f"/board.html?id={board['id']}")
    page.wait_for_function(
        f"() => document.querySelector('{MOBILE_VISIBILITY}')?.style.display === ''", timeout=8000
    )
    page.locator("#mobile-menu-toggle").click()
    page.locator("#mobile-board-actions summary").click()
    page.locator(MOBILE_STYLE).wait_for(state="visible", timeout=5000)

    assert pressed(page, MOBILE_VISIBILITY) == ["Private"]
    current = pressed(page, MOBILE_STYLE)[0]
    other = "Agile" if current == "Kanban" else "Kanban"

    page.locator(MOBILE_STYLE).get_by_role("button", name=other).click()

    page.wait_for_function(
        f"""() => document.querySelector('{MOBILE_STYLE} button[aria-pressed="true"]').textContent === '{other}'""",
        timeout=5000,
    )
    assert board_style(api_session, ui_base_url, board) == other.lower()

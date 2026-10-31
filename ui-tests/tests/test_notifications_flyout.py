"""UI tests for the notifications hover flyout in the desktop header."""
import uuid

import pytest


def _hover_bell(page, width):
    page.set_viewport_size({"width": width, "height": 800})
    page.goto("/profile.html")
    bell = page.locator("#notifications-icon-link")
    bell.wait_for(state="visible", timeout=8000)
    bell.hover()
    popup = page.locator("#notifications-popup")
    popup.wait_for(state="visible", timeout=8000)
    # The fade-in also moves the flyout, so measure it once it has settled.
    popup.evaluate("el => Promise.all(el.getAnimations().map(a => a.finished))")
    return bell.bounding_box(), popup


@pytest.mark.ui
@pytest.mark.parametrize("width", [1280, 950])
def test_mouse_can_move_from_bell_onto_flyout(logged_in_page, width):
    page = logged_in_page
    bell_box, popup = _hover_bell(page, width)
    x = bell_box["x"] + bell_box["width"] / 2
    start = bell_box["y"] + bell_box["height"] - 1
    end = popup.bounding_box()["y"] + 20

    # One pixel at a time, so the mouse also rests on any gap under the bell.
    y = start
    while y <= end:
        page.mouse.move(x, y)
        page.wait_for_timeout(20)
        assert popup.is_visible(), f"flyout closed with the mouse at y={y}"
        y += 1


@pytest.mark.ui
def test_flyout_header_fills_the_top_of_the_panel(logged_in_page):
    _, popup = _hover_bell(logged_in_page, 1280)

    assert popup.locator(".notifications-header").bounding_box()["y"] == popup.bounding_box()["y"]


@pytest.mark.ui
def test_flyout_can_be_used_with_the_mouse(logged_in_page, api_session, ui_base_url):
    subject = f"Flyout hover test {uuid.uuid4().hex[:8]}"
    response = api_session.post(
        f"{ui_base_url}/api/notifications",
        json={"subject": subject, "message": "Reachable by mouse"},
    )
    assert response.ok
    notification_id = response.json()["notification_id"]

    try:
        page = logged_in_page
        bell_box, popup = _hover_bell(page, 1280)
        item = popup.locator(".notification-item", has_text=subject)
        item.wait_for(state="visible", timeout=8000)
        item_box = item.bounding_box()

        page.mouse.move(bell_box["x"] + bell_box["width"] / 2, bell_box["y"] + bell_box["height"] - 1)
        page.mouse.move(item_box["x"] + 20, item_box["y"] + 10, steps=30)
        page.wait_for_timeout(100)
        assert popup.is_visible()

        item.locator(".delete-btn").click()
        item.wait_for(state="detached", timeout=8000)
        assert popup.is_visible()
    finally:
        api_session.delete(f"{ui_base_url}/api/notifications/{notification_id}")

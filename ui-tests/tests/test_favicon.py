"""UI tests for the favicon on pages that don't load header.js (issue #411)."""
import json

import pytest

pytestmark = pytest.mark.ui

DEFAULT_FAVICONS = ["/images/AFT_logo.png", "/images/AFT_logo.webp"]
LOGO_ENDPOINT = "**/api/branding/logo"
PAGES_WITHOUT_HEADER = ["/login.html", "/register.html", "/logout.html"]


def _favicon_hrefs(page):
    return page.eval_on_selector_all(
        "link[rel='icon']", "links => links.map(link => link.getAttribute('href'))"
    )


def _stub_logo(page, status, body):
    # context.route, because the service worker can make the request.
    page.context.route(
        LOGO_ENDPOINT,
        lambda route: route.fulfill(
            status=status, content_type="application/json", body=json.dumps(body)
        ),
    )


@pytest.mark.parametrize("path", PAGES_WITHOUT_HEADER)
def test_custom_logo_replaces_default_favicon(page, path):
    custom_path = "/images/backgrounds/logos/logo_custom.png"
    _stub_logo(page, 200, {"filename": "logo_custom.png"})

    page.goto(path)
    page.wait_for_function(
        "path => [...document.querySelectorAll(\"link[rel='icon']\")]"
        ".every(link => link.getAttribute('href') === path)",
        arg=custom_path,
    )

    assert page.locator("link[rel='icon'][type]").count() == 0


@pytest.mark.parametrize(
    "status, body", [(200, {"filename": None}), (500, {"error": "failed"})]
)
def test_default_favicon_stays_without_custom_logo(page, status, body):
    _stub_logo(page, status, body)

    with page.expect_response(LOGO_ENDPOINT) as logo_response:
        page.goto("/login.html")
    logo_response.value.finished()

    assert _favicon_hrefs(page) == DEFAULT_FAVICONS

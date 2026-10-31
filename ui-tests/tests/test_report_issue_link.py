"""UI tests for the Report an Issue links (issue #385)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

ISSUES_URL = "https://github.com/sjefferson99/aft/issues"
SECURITY_URL = "https://github.com/sjefferson99/aft/security/advisories/new"


def _assert_opens_in_new_tab(link):
    assert link.get_attribute("href") == ISSUES_URL
    assert link.get_attribute("target") == "_blank"
    assert "noopener" in link.get_attribute("rel")


def test_user_menu_links_to_github_issues(logged_in_page):
    page = logged_in_page
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/docs.html")
    page.locator(".user-dropdown").hover()

    link = page.locator("#report-issue-menu-item")
    link.wait_for(state="visible", timeout=8000)
    _assert_opens_in_new_tab(link)


def test_mobile_menu_links_to_github_issues(logged_in_page):
    page = logged_in_page
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto("/docs.html")
    page.locator("#mobile-menu-toggle").click()
    page.locator("#mobile-menu-drawer summary", has_text="User").click()

    link = page.locator("#mobile-report-issue-menu-item")
    link.wait_for(state="visible", timeout=8000)
    _assert_opens_in_new_tab(link)


def test_docs_send_security_reports_to_private_route(page):
    page.goto("/docs.html")
    section = page.locator("#docs-content")

    expect(section.locator(f"a[href='{SECURITY_URL}']")).to_be_visible()
    expect(section.locator(f"a[href='{ISSUES_URL}']").first).to_be_visible()

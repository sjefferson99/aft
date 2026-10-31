"""The Docs page renders the Markdown guides in www/docs (#630)."""
import re

import pytest
from playwright.sync_api import expect


@pytest.fixture
def docs_page(page):
    page.goto("/docs.html")
    expect(page.locator("#docs-toc")).to_be_visible()
    return page


def test_guides_render_into_panels(docs_page):
    content = docs_page.locator("#docs-content")

    for title in ("About AFT", "User Guide", "Administration"):
        expect(content.locator("h1", has_text=title)).to_be_visible()

    expect(content.locator("section.docs-section h2", has_text="Keyboard Shortcuts")).to_be_visible()
    expect(content.locator("table kbd", has_text="N").first).to_be_visible()


def test_table_of_contents_links_to_sections(docs_page):
    docs_page.locator("#docs-toc a", has_text="Passkeys").click()

    expect(docs_page).to_have_url(re.compile(r"#passkeys$"))
    expect(docs_page.locator("#passkeys")).to_be_in_viewport()


def test_deep_link_scrolls_to_a_section_after_rendering(page):
    page.goto("/docs.html#working-style")

    expect(page.locator("#working-style")).to_be_in_viewport()
    assert page.evaluate("window.scrollY") > 0


def test_every_anchor_is_unique_and_every_internal_link_resolves(docs_page):
    ids = docs_page.evaluate(
        "Array.from(document.querySelectorAll('#docs-content [id]')).map((element) => element.id)"
    )
    assert len(ids) == len(set(ids))

    broken = docs_page.evaluate("""
        Array.from(document.querySelectorAll('#docs-content a[href^="#"]'))
          .map((link) => link.getAttribute('href'))
          .filter((href) => !document.getElementById(decodeURIComponent(href.slice(1))))
    """)
    assert broken == []


def test_links_between_guides_stay_on_the_page(docs_page):
    relative_guides = docs_page.evaluate("""
        Array.from(document.querySelectorAll('#docs-content a'))
          .map((link) => link.getAttribute('href'))
          .filter((href) => href.includes('.md') && !href.startsWith('http'))
    """)
    assert relative_guides == []


def test_external_links_open_in_a_new_tab(docs_page):
    link = docs_page.locator('#docs-content a[href="https://github.com/sjefferson99/aft"]').first

    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")


def test_images_load(docs_page):
    docs_page.wait_for_load_state("load")
    images = docs_page.locator("#docs-content img")

    assert images.count() > 0
    broken = docs_page.evaluate("""
        Promise.all(Array.from(document.querySelectorAll('#docs-content img')).map(async (image) => {
          await image.decode().catch(() => {});
          return image.naturalWidth ? null : image.src;
        })).then((sources) => sources.filter(Boolean))
    """)
    assert broken == []


def test_wide_tables_do_not_widen_a_phone_screen(page):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto("/docs.html")
    expect(page.locator("#docs-toc")).to_be_visible()

    assert page.evaluate("document.documentElement.scrollWidth") <= 390


def test_script_in_markdown_is_removed(context, page):
    context.route("**/docs/README.md", lambda route: route.fulfill(
        status=200,
        content_type="text/markdown",
        body='# About AFT\n\n<img src=x onerror="window.docsXss = true">\n\n<script>window.docsXss = true</script>',
    ))
    page.goto("/docs.html")
    expect(page.locator("#docs-toc")).to_be_visible()

    assert page.evaluate("window.docsXss") is None
    assert page.locator("#docs-content script").count() == 0
    assert page.locator("#docs-content img[onerror]").count() == 0


def test_shows_a_message_when_a_guide_fails_to_load(context, page):
    context.route("**/docs/user-guide.md", lambda route: route.fulfill(status=500, body=""))
    page.goto("/docs.html")

    expect(page.locator("#docs-content")).to_contain_text("could not be loaded")


def test_missing_doc_is_a_real_404(page):
    response = page.request.get("/docs/no-such-guide.md")

    assert response.status == 404


def test_about_page_is_gone(logged_in_page):
    logged_in_page.goto("/docs.html")
    expect(logged_in_page.locator("#docs-toc")).to_be_visible()

    links = logged_in_page.locator('a[href="/about.html"]')
    assert links.count() == 0
    assert logged_in_page.request.get("/about.html").status == 404

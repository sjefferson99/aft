"""UI tests for the theme builder page."""
import pytest


@pytest.mark.ui
def test_apply_theme_confirmation_visible_without_scrolling(logged_in_page):
    """Applying a theme shows its confirmation in the visible viewport, not
    in a status line at the bottom of the long page (#511)."""
    page = logged_in_page
    page.set_viewport_size({'width': 1280, 'height': 720})
    page.goto('/theme-builder.html')
    page.wait_for_function(
        "document.querySelectorAll('#theme-builder-select option').length > 0"
    )
    # Button listeners are attached only once themes and background images
    # have both loaded.
    page.wait_for_load_state('networkidle')

    page.click('#apply-theme-btn')

    toast = page.locator('.header-inline-toast', has_text='Theme applied')
    toast.wait_for(state='visible', timeout=5000)
    assert page.evaluate('window.scrollY') == 0

    box = toast.bounding_box()
    assert box is not None
    assert box['y'] >= 0
    assert box['y'] + box['height'] <= 720

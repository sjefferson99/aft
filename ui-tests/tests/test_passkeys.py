"""UI tests for passkeys (issue #546): profile management, passkey sign-in and admin revoke.

Uses Chromium's virtual authenticator (CDP WebAuthn domain), so no real device
is needed. Needs passkeys enabled on the stack under test: for http://localhost
set WEBAUTHN_RP_ID=localhost and WEBAUTHN_ORIGINS=http://localhost in .env.
"""
import os
import uuid

import pytest
import requests

UI_BASE_URL = os.getenv("PYTEST_UI_BASE_URL", "http://localhost")


def _passkeys_enabled():
    try:
        response = requests.get(f"{UI_BASE_URL}/api/auth/passkeys/status", timeout=5)
        return response.status_code == 200 and response.json().get("enabled") is True
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def require_passkeys(ensure_test_admin):
    """Skip when passkeys are off. Checked after setup: before the first admin
    exists every API call, including the status endpoint, returns 503."""
    if not _passkeys_enabled():
        pytest.skip(
            "Passkeys not enabled on the stack (set WEBAUTHN_RP_ID=localhost and "
            "WEBAUTHN_ORIGINS=http://localhost,https://localhost in .env)"
        )


def add_virtual_authenticator(page):
    """Attach a platform-style authenticator with biometrics to this page's browser tab."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("WebAuthn.enable", {"enableUI": False})
    cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
        "protocol": "ctap2",
        "transport": "internal",
        "hasResidentKey": True,
        "hasUserVerification": True,
        "isUserVerified": True,
        "automaticPresenceSimulation": True,
    }})
    return cdp


@pytest.fixture
def passkey_user(api_session):
    """A fresh, approved user with known credentials (keeps passkeys off test-admin)."""
    suffix = uuid.uuid4().hex[:8]
    user = {
        "email": f"ui-passkey-{suffix}@localhost",
        "username": f"ui-passkey-{suffix}",
        "password": f"UiPasskey-{uuid.uuid4().hex[:12]}-Aa1!",
    }
    response = requests.post(f"{UI_BASE_URL}/api/auth/register", json={
        **user, "display_name": f"UI Passkey {suffix}",
    }, timeout=5)
    assert response.status_code == 201, response.text
    body = response.json()
    user["id"] = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")
    approve = api_session.post(f"{UI_BASE_URL}/api/users/{user['id']}/approve")
    assert approve.status_code == 200, approve.text
    return user


def login_with_password(page, user):
    page.goto("/login.html")
    page.fill("#email", user["email"])
    page.fill("#password", user["password"])
    page.click("#loginButton")
    page.wait_for_url(lambda url: "login.html" not in url, timeout=10000)


def add_passkey(page, user, name):
    """Add a passkey from the profile page and wait for it to be listed."""
    page.goto("/profile.html")
    page.locator("#passkeys-section").wait_for(state="visible", timeout=10000)
    page.click("#add-passkey-btn")
    page.fill("#add-passkey-password", user["password"])
    page.fill("#add-passkey-name", name)
    page.click("#add-passkey-ok-btn")
    page.locator("#passkey-list .passkey-name", has_text=name).wait_for(timeout=10000)


def test_add_rename_and_remove_passkey(page, passkey_user):
    """A user can add a passkey from their profile, rename it and remove it."""
    add_virtual_authenticator(page)
    login_with_password(page, passkey_user)
    add_passkey(page, passkey_user, "Test laptop")

    assert page.locator("#passkey-empty").is_hidden()
    assert "Passkey added" in page.locator("#passkey-status").inner_text()

    page.click('button[aria-label="Rename passkey Test laptop"]')
    page.fill("#rename-passkey-name", "Work laptop")
    page.click("#rename-passkey-ok-btn")
    page.locator("#passkey-list .passkey-name", has_text="Work laptop").wait_for(timeout=5000)

    page.click('button[aria-label="Remove passkey Work laptop"]')
    assert page.locator("#remove-passkey-modal").is_visible()
    page.click("#remove-passkey-ok-btn")
    page.locator("#passkey-empty").wait_for(state="visible", timeout=5000)
    assert page.locator("#passkey-list li").count() == 0
    assert "profile.html" in page.url, "password session must survive removing a passkey"


def test_wrong_password_keeps_user_signed_in(page, passkey_user):
    """A wrong password shows an error in the dialog and doesn't sign the user out."""
    add_virtual_authenticator(page)
    login_with_password(page, passkey_user)
    page.goto("/profile.html")
    page.locator("#passkeys-section").wait_for(state="visible", timeout=10000)

    page.click("#add-passkey-btn")
    page.fill("#add-passkey-password", f"wrong-{uuid.uuid4().hex}")
    page.click("#add-passkey-ok-btn")

    error = page.locator("#add-passkey-error")
    error.wait_for(state="visible", timeout=5000)
    assert "incorrect" in error.inner_text().lower()
    assert page.locator("#add-passkey-modal").is_visible()
    assert "profile.html" in page.url


def assert_signed_in_as(page, user):
    page.wait_for_url(lambda url: "login.html" not in url, timeout=10000)
    page.locator("#boards-container").wait_for(state="visible", timeout=5000)
    check = page.request.get(f"{UI_BASE_URL}/api/auth/check")
    assert check.ok
    assert check.json()["user"]["id"] == user["id"]


def test_sign_in_with_passkey_autofill(page, passkey_user):
    """Passkeys are offered in username autofill.

    Chromium's virtual authenticator answers the autofill request straight
    away, where a real browser waits for the user to pick the passkey, so the
    page signs in on load.
    """
    add_virtual_authenticator(page)
    login_with_password(page, passkey_user)
    add_passkey(page, passkey_user, "Autofill key")

    page.context.clear_cookies()
    page.goto("/login.html")
    assert page.get_attribute("#email", "autocomplete") == "username webauthn"
    assert_signed_in_as(page, passkey_user)


def test_sign_in_with_passkey_button(page, passkey_user):
    """The "Sign in with a passkey" button signs in where autofill isn't available."""
    add_virtual_authenticator(page)
    login_with_password(page, passkey_user)
    add_passkey(page, passkey_user, "Button key")

    page.add_init_script("""
        if (window.PublicKeyCredential) {
            PublicKeyCredential.isConditionalMediationAvailable = async () => false;
        }
    """)
    page.context.clear_cookies()
    page.goto("/login.html")
    button = page.locator("#passkeyButton")
    button.wait_for(state="visible", timeout=5000)
    assert "login.html" in page.url

    button.click()
    assert_signed_in_as(page, passkey_user)


def test_cancelled_passkey_prompt_shows_error(page):
    """If the user cancels the browser prompt, the login page shows an error and stays put."""
    page.goto("/login.html")
    page.locator("#passkeyButton").wait_for(state="visible", timeout=5000)
    # Simulate the user cancelling the browser's passkey prompt.
    page.evaluate("""() => {
        navigator.credentials.get = () =>
            Promise.reject(new DOMException('cancelled', 'NotAllowedError'));
    }""")
    page.click("#passkeyButton")

    error = page.locator("#errorMessage")
    error.wait_for(state="visible", timeout=5000)
    assert "cancelled" in error.inner_text().lower()
    assert "login.html" in page.url
    assert page.locator("#passkeyButton").is_enabled()


def test_admin_can_revoke_passkeys(browser, logged_in_page, passkey_user):
    """An admin sees a user's passkeys and can revoke them from User Management."""
    user_context = browser.new_context(base_url=UI_BASE_URL)
    try:
        user_page = user_context.new_page()
        add_virtual_authenticator(user_page)
        login_with_password(user_page, passkey_user)
        add_passkey(user_page, passkey_user, "Lost phone")
    finally:
        user_context.close()

    page = logged_in_page
    page.goto("/user-management.html")
    card = page.locator(f'.active-user-card[data-user-id="{passkey_user["id"]}"]')
    card.wait_for(timeout=10000)
    assert "Passkeys: 1" in card.inner_text()

    card.locator('[data-action="revoke-passkeys"]').click()
    page.locator("#confirm-modal").wait_for(state="visible", timeout=5000)
    page.click("#confirm-ok-btn")

    page.locator(
        f'.active-user-card[data-user-id="{passkey_user["id"]}"] [data-action="revoke-passkeys"]'
    ).wait_for(state="detached", timeout=10000)
    assert "Passkeys:" not in page.locator(
        f'.active-user-card[data-user-id="{passkey_user["id"]}"]'
    ).inner_text()

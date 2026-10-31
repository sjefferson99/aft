"""Takes the docs screenshots from a stack running generic demo data.

Start the throwaway stack first, so the images can't show real data:

    docker compose -f compose.yml -f compose.screenshots.yml up -d --build

Then retake only the images a change altered, because every image stays in git
history for good:

    python scripts/screenshots.py board card_detail
    python scripts/screenshots.py --list

See docs/SCREENSHOTS.md. Needs Playwright, from ui-tests/requirements-dev.txt.
"""
import argparse
import datetime
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("AFT_SCREENSHOT_URL", "http://localhost")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "www" / "images" / "docs"
VIEWPORT = {"width": 1440, "height": 860}
# Made when seeding and kept here, so later runs can sign in to the same stack.
PASSWORD_FILE = Path(tempfile.gettempdir()) / "aft-screenshots-password"

ADMIN = {
    "email": "sam.taylor@example.com",
    "username": "sam.taylor",
    "display_name": "Sam Taylor",
}
TEAM = [
    ("priya.shah", "Priya Shah"),
    ("jordan.lee", "Jordan Lee"),
    ("maria.garcia", "Maria Garcia"),
]
MOVE_BOARD = "Office Move"
AGILE_BOARD = "Website Launch"
SCHEDULE_BOARD = "Building Maintenance"

SHOTS = {}
BOARD_IDS = {}


def demo_password():
    return PASSWORD_FILE.read_text() if PASSWORD_FILE.exists() else ""


def shot(function):
    """Registers a screenshot under the name of its function, which is its image name."""
    SHOTS[function.__name__] = function
    return function


class Api:
    """Calls the API as the demo admin, sending the Secure session cookie over http://localhost."""

    def __init__(self):
        self.session = requests.Session()

    def call(self, method, path, **kwargs):
        response = self.session.request(method, f"{BASE_URL}{path}", timeout=30, **kwargs)
        if not response.ok:
            sys.exit(f"{method} {path} failed: HTTP {response.status_code} {response.text[:300]}")
        return response.json()

    def login(self):
        """Signs in, returning False if this isn't a demo database."""
        credentials = {"email": ADMIN["email"], "password": demo_password()}
        response = self.session.post(f"{BASE_URL}/api/auth/login", json=credentials, timeout=30)
        if response.status_code != 200:
            return False
        for cookie in [c for c in self.session.cookies if c.secure]:
            self.session.cookies.set(cookie.name, cookie.value, path=cookie.path or "/", secure=False)
        return True

    def column(self, board_id, name):
        return self.call("POST", f"/api/boards/{board_id}/columns", json={"name": name})["column"]["id"]

    def card(self, column_id, title, description="", checklist=(), comments=(), days=None):
        """Adds a card. ``days`` is its start and end, as day offsets from today."""
        body = {"title": title, "description": description}
        if days:
            start, end = (datetime.datetime.now() + datetime.timedelta(days=d) for d in days)
            body["start_date"] = start.strftime("%Y-%m-%dT09:00:00")
            body["end_date"] = end.strftime("%Y-%m-%dT17:00:00")
        card_id = self.call("POST", f"/api/columns/{column_id}/cards", json=body)["card"]["id"]
        for name, checked in checklist:
            self.call("POST", f"/api/cards/{card_id}/checklist-items", json={"name": name, "checked": checked})
        for comment in comments:
            self.call("POST", f"/api/cards/{card_id}/comments", json={"comment": comment})
        return card_id


def seed_move_board(api):
    board_id = api.call("POST", "/api/boards", json={
        "name": MOVE_BOARD, "description": "Moving the team to the new office",
    })["board"]["id"]
    api.call("PUT", f"/api/boards/{board_id}/settings/working-style", json={"value": "kanban"})

    todo = api.column(board_id, "To Do")
    doing = api.column(board_id, "In Progress")
    waiting = api.column(board_id, "Waiting")
    done = api.column(board_id, "Done")

    api.card(todo, "Book the removal company", "Get three quotes and check their insurance.", days=(2, 4))
    api.card(todo, "Order new desks", "Sit-stand desks for the second floor.", days=(5, 12))
    api.card(todo, "Update the company address", checklist=[
        ("Website", False), ("Bank", False), ("Suppliers", False),
    ], days=(9, 9))
    api.card(todo, "Plan the seating layout", "Keep project teams together.")
    api.card(doing, "Set up the network", "New switches and Wi-Fi access points on both floors.", checklist=[
        ("Survey the building", True),
        ("Order switches", True),
        ("Install access points", False),
        ("Test Wi-Fi coverage", False),
    ], comments=[
        "The survey is booked for Tuesday.",
        "Switches have arrived and are in the comms room.",
    ], days=(-3, 6))
    api.card(doing, "Pack the meeting rooms", "Crates are in the post room.", days=(1, 3))
    api.card(waiting, "Landlord sign-off", "Waiting for the signed lease.", comments=["Chased on Monday."], days=(3, 3))
    api.card(done, "Sign the lease", days=(-12, -12))
    api.card(done, "Measure the new floors", days=(-9, -8))
    for title in ("Compare office locations", "Set the moving budget"):
        api.call("PATCH", f"/api/cards/{api.card(done, title)}/archive")


def seed_agile_board(api):
    board_id = api.call("POST", "/api/boards", json={
        "name": AGILE_BOARD, "description": "Everything for the new website",
    })["board"]["id"]
    api.call("PUT", f"/api/boards/{board_id}/settings/working-style", json={"value": "agile"})

    columns = {
        "Design": [("Choose the colour palette", True), ("Draw the home page", True), ("Draw the pricing page", False)],
        "Build": [("Set up hosting", True), ("Build the contact form", False), ("Add the blog", False)],
        "Launch": [("Check every link", False), ("Announce the launch", False)],
    }
    for name, cards in columns.items():
        column_id = api.column(board_id, name)
        for title, done in cards:
            card_id = api.card(column_id, title)
            if done:
                api.call("PATCH", f"/api/cards/{card_id}/done", json={"done": True})


def seed_schedule_board(api):
    board_id = api.call("POST", "/api/boards", json={
        "name": SCHEDULE_BOARD, "description": "Regular jobs that come round again",
    })["board"]["id"]
    api.call("PUT", f"/api/boards/{board_id}/settings/working-style", json={"value": "kanban"})

    column_id = api.column(board_id, "This Week")
    api.column(board_id, "Done")
    start = datetime.datetime.now() + datetime.timedelta(days=2)
    schedules = [
        ("Test the fire alarms", "Press a different call point each week.", "week"),
        ("Put the bins out", "Recycling and general waste.", "week"),
        ("Check the first aid kits", "Replace anything used or out of date.", "month"),
        ("Service the boiler", "Book the engineer two weeks ahead.", "year"),
    ]
    for title, description, unit in schedules:
        card_id = api.card(column_id, title, description, checklist=[("Record it in the log", False)])
        api.call("POST", "/api/schedules", json={
            "card_id": card_id,
            "run_every": 1,
            "unit": unit,
            "start_datetime": start.strftime("%Y-%m-%dT09:00:00"),
            "schedule_enabled": True,
            "keep_source_card": False,
        })


def seed_team(api):
    for username, display_name in TEAM:
        user = api.call("POST", "/api/auth/register", json={
            "email": f"{username}@example.com",
            "username": username,
            "password": demo_password(),
            "display_name": display_name,
        })["user"]
        api.call("POST", f"/api/users/{user['id']}/approve")


def seed_notifications(api):
    api.call("POST", "/api/notifications", json={
        "subject": "Backup overdue",
        "message": "The scheduled backup hasn't run. Check the backup settings.",
        "action_title": "Open Backups",
        "action_url": "/backup-restore.html",
    })
    api.call("POST", "/api/notifications", json={
        "subject": "Schedule ended",
        "message": "A schedule on Building Maintenance reached its end date.",
    })


def seed_backups(api):
    """Runs a real scheduled backup, because the page's status ignores manual ones."""
    config = {"enabled": True, "start_time": "00:00", "retention_count": 7}
    api.call("PUT", "/api/settings/backup/config", json={
        **config, "frequency_value": 1, "frequency_unit": "minutes",
    })
    print("Waiting for the scheduled backup, which can take a couple of minutes...")
    deadline = time.time() + 240
    while not api.call("GET", "/api/settings/backup/status")["status"].get("latest_backup_date"):
        if time.time() > deadline:
            sys.exit("The scheduled backup didn't run.")
        time.sleep(5)
    api.call("PUT", "/api/settings/backup/config", json={
        **config, "frequency_value": 1, "frequency_unit": "daily",
    })


def seed(api):
    seed_team(api)
    seed_move_board(api)
    seed_agile_board(api)
    seed_schedule_board(api)
    seed_notifications(api)
    seed_backups(api)


def connect():
    """Signs in as the demo admin, seeding a brand-new database first."""
    api = Api()
    status = requests.get(f"{BASE_URL}/api/auth/setup/status", timeout=30)
    status.raise_for_status()

    if status.json().get("setup_complete"):
        if not api.login():
            sys.exit("This database wasn't seeded by this script, so it may hold real data. "
                     "Start the throwaway stack: see docs/SCREENSHOTS.md.")
    else:
        PASSWORD_FILE.write_text(f"Aa1!{secrets.token_urlsafe(24)}")
        api.call("POST", "/api/auth/setup/admin", json={**ADMIN, "password": demo_password()})
        if not api.login():
            sys.exit("Couldn't sign in as the demo admin.")
        seed(api)

    BOARD_IDS.update({item["name"]: item["id"] for item in api.call("GET", "/api/boards")["boards"]})


def open_board(page, name):
    page.goto(f"/board.html?id={BOARD_IDS[name]}")
    expect(page.get_by_role("button", name="+ Add Column")).to_be_visible()


def open_scheduled_view(page):
    open_board(page, SCHEDULE_BOARD)
    switch_view(page, "scheduled")
    expect(page.locator(".card", has_text="Test the fire alarms")).to_be_visible()


def switch_view(page, view):
    page.locator("#views-dropdown-btn").click()
    page.locator(f'.views-dropdown-item[data-view="{view}"]').click()


def save(target, name):
    """Saves a page, or a locator cropped to that element."""
    target.screenshot(path=OUTPUT_DIR / f"{name}.png", animations="disabled", caret="hide")


@shot
def boards(page):
    page.goto("/")
    expect(page.locator(".canvas").get_by_text(MOVE_BOARD)).to_be_visible()
    save(page, "boards")


@shot
def board(page):
    open_board(page, MOVE_BOARD)
    save(page, "board")


@shot
def card_detail(page):
    open_board(page, MOVE_BOARD)
    page.locator(".card", has_text="Set up the network").click()
    expect(page.locator("#edit-card-modal")).to_be_visible()
    page.wait_for_timeout(500)
    page.evaluate("document.activeElement.blur()")
    save(page, "card_detail")


@shot
def archive_screen(page):
    open_board(page, MOVE_BOARD)
    switch_view(page, "archived")
    expect(page.get_by_text("Set the moving budget")).to_be_visible()
    save(page, "archive_screen")


@shot
def scheduled_cards(page):
    open_scheduled_view(page)
    save(page, "scheduled_cards")


@shot
def schedule_modal(page):
    open_scheduled_view(page)
    page.locator(".card", has_text="Test the fire alarms").click()
    expect(page.locator("#edit-card-modal")).to_be_visible()
    page.locator("#edit-schedule-from-template-btn").click()
    expect(page.locator("#schedule-modal")).to_be_visible()
    page.wait_for_timeout(500)
    save(page, "schedule_modal")


@shot
def planner(page):
    open_board(page, MOVE_BOARD)
    switch_view(page, "planner")
    expect(page.locator(".planner-toolbar")).to_be_visible()
    page.wait_for_timeout(1000)
    save(page, "planner")


@shot
def working_style_options(page):
    page.goto("/profile.html")
    expect(page.locator("#working-style option", has_text="Kanban")).to_have_count(1)
    save(page.locator(".setting-item", has=page.locator("#working-style")), "working_style_options")


@shot
def done_button_and_counts(page):
    open_board(page, AGILE_BOARD)
    page.wait_for_timeout(500)
    save(page, "done_button_and_counts")


@shot
def done_task_view(page):
    open_board(page, AGILE_BOARD)
    switch_view(page, "done")
    page.wait_for_timeout(1000)
    save(page, "done_task_view")


@shot
def preferences(page):
    page.goto("/profile.html#preferences")
    expect(page.locator("#working-style option", has_text="Kanban")).to_have_count(1)
    page.wait_for_timeout(500)
    save(page.locator("#preferences"), "preferences")


@shot
def theme_builder(page):
    page.goto("/theme-builder.html")
    page.wait_for_timeout(1500)
    save(page, "theme_builder")


@shot
def notifications(page):
    page.goto("/")
    expect(page.locator("#notification-badge")).to_be_visible()
    page.locator("#notifications-icon-link").click()
    expect(page.locator("#notifications-popup")).to_be_visible()
    page.wait_for_timeout(500)
    save(page, "notifications")


@shot
def backup_configuration(page):
    page.goto("/backup-restore.html")
    expect(page.locator("#latestBackup")).not_to_have_text("-")
    page.wait_for_timeout(500)
    save(page, "backup_configuration")


@shot
def system_info(page):
    page.goto("/system-info.html")
    page.wait_for_timeout(1500)
    save(page, "system_info")


@shot
def user_management(page):
    page.goto("/settings.html#users")
    page.wait_for_timeout(1500)
    save(page, "user_management")


@shot
def api_docs(page):
    page.goto("/api/docs")
    expect(page.locator(".swagger-ui .info")).to_be_visible()
    page.wait_for_timeout(500)
    save(page, "api_docs")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="*", help="image names, without .png")
    parser.add_argument("--list", action="store_true", help="list the image names")
    args = parser.parse_args()

    if args.list or not args.images:
        print("\n".join(SHOTS))
        return

    unknown = set(args.images) - set(SHOTS)
    if unknown:
        parser.error(f"unknown images: {', '.join(sorted(unknown))}")

    connect()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(base_url=BASE_URL, viewport=VIEWPORT, locale="en-GB")
        page = context.new_page()
        page.goto("/login.html")
        page.fill("#email", ADMIN["email"])
        page.fill("#password", demo_password())
        page.click("#loginButton")
        page.wait_for_url(lambda url: "login.html" not in url)

        page.close()

        # A page each, so a popup left open can't appear in the next image.
        for name in args.images:
            page = context.new_page()
            SHOTS[name](page)
            page.close()
            print(f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main()

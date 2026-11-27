#!/usr/bin/env python3
"""Show AFT host status on a Pimoroni Inky pHAT e-ink display.

Shows the URL clients connect to (hostname, with the IP address below), AFT
health, load average, memory and swap use, and basic AFT counts, including
users who signed in and cards edited in the last 24 hours. Counts come from
read-only queries run inside the aft-db container with the credentials already
in its environment, so no AFT login is stored here and no server changes are
needed.

While the Wi-Fi hotspot fallback (#725) has the hotspot up, it shows how to
join it instead: the network name, password and address, with a Wi-Fi QR code
if python3-qrcode is installed.

Run with --preview out.png to render without a display.
Settings come from environment variables, see aft-inky-status.env.
"""

import argparse
import http.client
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

WHITE, BLACK, COLOUR = 0, 1, 2
HOTSPOT_CONNECTION = "aft-hotspot"
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
STATS_SQL = (
    "SELECT "
    "(SELECT COUNT(*) FROM boards WHERE archived = 0),"
    "(SELECT COUNT(*) FROM cards WHERE archived = 0),"
    "(SELECT COUNT(*) FROM users WHERE is_active = 1 AND last_login_at >= NOW() - INTERVAL 1 DAY),"
    "(SELECT COUNT(*) FROM cards WHERE updated_at >= NOW() - INTERVAL 1 DAY)"
)


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Settings:
    def __init__(self):
        self.poll = max(5, env_int("AFT_INKY_POLL", 30))
        self.unhealthy_poll = max(5, env_int("AFT_INKY_UNHEALTHY_POLL", 10))
        self.min_redraw = max(30, env_int("AFT_INKY_MIN_REDRAW", 60))
        self.containers = os.environ.get("AFT_CONTAINERS", "aft-db aft-redis aft-server aft-web").split()
        self.db_container = os.environ.get("AFT_DB_CONTAINER", "aft-db")
        self.health_url = os.environ.get("AFT_HEALTH_URL", "http://127.0.0.1/api/health/live")
        self.scheme = os.environ.get("AFT_URL_SCHEME", "https")
        self.host = os.environ.get("AFT_URL_HOST") or socket.gethostname().lower()
        self.timeout = env_int("AFT_QUERY_TIMEOUT", 20)
        self.flip = os.environ.get("AFT_INKY_FLIP", "0") == "1"


def get_ip():
    """Address of the interface holding the default route. Sends no packets."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
        except OSError:
            return None


def has_wireless():
    try:
        return any(os.path.isdir(f"/sys/class/net/{name}/wireless") for name in os.listdir("/sys/class/net"))
    except OSError:
        return False


def hotspot_info(settings):
    """Return {"ssid", "password", "address"} while the AFT hotspot is up, else None."""
    rc, out = run(
        ["nmcli", "-s", "-t", "-e", "no", "-f",
         "GENERAL.STATE,802-11-wireless.ssid,802-11-wireless-security.psk,IP4.ADDRESS",
         "connection", "show", "id", HOTSPOT_CONNECTION],
        settings.timeout,
    )
    return parse_hotspot(out) if rc == 0 else None


def parse_hotspot(out):
    """Parse nmcli -t -f output. Only an active hotspot counts.

    The output is keyed by field, because nmcli leaves out fields with no
    value: an inactive connection has no GENERAL.STATE or IP4.ADDRESS line.
    """
    fields = {}
    for line in out.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields.setdefault(key.split("[")[0], value)
    if fields.get("GENERAL.STATE") != "activated":
        return None
    address = fields.get("IP4.ADDRESS", "").split("/")[0] or "10.42.0.1"
    return {"ssid": fields.get("802-11-wireless.ssid", ""),
            "password": fields.get("802-11-wireless-security.psk", ""), "address": address}


def wifi_qr_payload(ssid, password):
    """The Wi-Fi QR code text phones understand, with its special characters escaped."""
    def esc(value):
        return "".join("\\" + c if c in '\\;,:"' else c for c in value)
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


def qr_matrix(text):
    """QR code modules as rows of booleans, or None without python3-qrcode."""
    try:
        import qrcode
    except ImportError:
        return None
    qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def read_meminfo():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            info[key] = int(value.split()[0]) // 1024  # MiB
    return info


def run(cmd, timeout):
    """Run a command, returning (returncode, stdout). Never raises."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout
    except (OSError, subprocess.SubprocessError):
        return None, ""


def container_problem(settings):
    """Return the first container problem as text, or None if all are fine."""
    rc, out = run(
        ["docker", "inspect", "--format",
         "{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
         *settings.containers],
        settings.timeout,
    )
    if rc is None:
        return "Docker not responding"
    states = {}
    for line in out.splitlines():
        parts = line.split()
        if parts:
            states[parts[0].lstrip("/")] = parts[1:]
    for name in settings.containers:
        short = name.removeprefix("aft-")
        state = states.get(name)
        if not state:
            return f"Missing: {short}"
        status, health = state[0], (state[1] if len(state) > 1 else "")
        if status == "restarting":
            return f"Restarting: {short}"
        if status != "running":
            return f"Down: {short}"
        if health == "starting":
            return f"Starting: {short}"
        if health == "unhealthy":
            return f"Unhealthy: {short}"
    return None


def web_ok(settings):
    try:
        with urllib.request.urlopen(settings.health_url, timeout=settings.timeout) as response:
            return response.status == 200
    except (OSError, ValueError, http.client.HTTPException):
        return False


def get_aft_stats(settings):
    """Return (boards, cards, signed_in_24h, changed_24h), or None if the query fails.

    signed_in_24h counts users whose last sign-in was in the last day. AFT has
    no record of activity within a session, so this is the closest measure
    of active users available without server changes.
    """
    rc, out = run(
        ["docker", "exec", settings.db_container, "sh", "-c",
         'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -N -B -e "$0"',
         STATS_SQL],
        settings.timeout,
    )
    try:
        values = [int(v) for v in out.split()]
    except ValueError:
        return None
    return tuple(values) if rc == 0 and len(values) == 4 else None


def collect(settings):
    mem = read_meminfo()
    problem = container_problem(settings)
    # Skip the query when the db container itself is down ("Down: db").
    stats = get_aft_stats(settings) if problem is None or "db" not in problem else None
    if problem is None and not web_ok(settings):
        problem = "Web not responding"
    if problem is None and stats is None:
        problem = "DB query failed"
    hotspot = hotspot_info(settings)
    # The hotspot has no default route, so take its own address.
    ip = hotspot["address"] if hotspot else get_ip()
    if problem is None and ip is None:
        problem = "No Wi-Fi" if has_wireless() else "No network"
    return {
        "ip": ip,
        "hotspot": hotspot,
        "problem": problem,
        "load": os.getloadavg(),
        "mem_used": mem["MemTotal"] - mem["MemAvailable"],
        "mem_total": mem["MemTotal"],
        "swap_used": mem["SwapTotal"] - mem["SwapFree"],
        "swap_total": mem["SwapTotal"],
        "aft": stats,
    }


def fmt_mib(mib):
    return f"{mib / 1024:.1f}G" if mib >= 1000 else f"{mib}M"


def build_screen(status, settings):
    """Return (lines, footer_left). Lines are (text, colour, bold), with values
    rounded so small changes don't force a slow e-ink refresh."""
    hotspot = status.get("hotspot")
    if hotspot:
        lines = [
            ("Join Wi-Fi", COLOUR, True),
            (hotspot["ssid"], BLACK, True),
            (hotspot["password"], BLACK, True),
            (f"{settings.scheme}://{hotspot['address']}/", COLOUR, True),
        ]
        if status["problem"]:
            lines.append((status["problem"], COLOUR, True))
            return lines, "AFT NOT OK"
        if status["aft"] is not None:
            lines.append((f"Boards {status['aft'][0]}  Cards {status['aft'][1]}", BLACK, False))
        return lines, "AFT OK"
    l1, l5, l15 = status["load"]
    lines = [
        (f"{settings.scheme}://{settings.host}/", COLOUR, True),
        (f"Load {l1:.1f} {l5:.1f} {l15:.1f}", BLACK, False),
        (f"Mem {fmt_mib(status['mem_used'])}/{fmt_mib(status['mem_total'])}"
         f"  Swap {fmt_mib(status['swap_used'])}/{fmt_mib(status['swap_total'])}", BLACK, False),
    ]
    if status["aft"] is not None:
        boards, cards, signed_in, changed = status["aft"]
        lines.append((f"Boards {boards}  Cards {cards}", BLACK, True))
    if status["problem"]:
        lines.append((status["problem"], COLOUR, True))
        return lines, "AFT NOT OK"
    lines.append((f"24h: {signed_in} signed in, {changed} cards edited", BLACK, False))
    return lines, "AFT OK"


def load_font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except OSError:
        return ImageFont.load_default(size)


def fit_font(draw, text, size, bold, max_width):
    font = load_font(size, bold)
    while size > 7 and draw.textlength(text, font=font) > max_width:
        size -= 1
        font = load_font(size, bold)
    return font


def draw_qr(draw, matrix, right, height, margin):
    """Draw the QR code against the right edge, as big as fits. Returns its left x."""
    modules = len(matrix)
    scale = (height - 2 * margin) // modules
    if scale < 2:
        return right
    side = modules * scale
    left = right - side
    top = (height - side) // 2
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                draw.rectangle((left + x * scale, top + y * scale,
                                left + (x + 1) * scale - 1, top + (y + 1) * scale - 1), fill=BLACK)
    return left


def render(size, lines, footer_left, footer_right, footer_mid="", qr=None):
    """Draw the screen onto a palette image the size of the display.

    With a QR matrix, the code goes on the right and the text and footer fit
    beside it, leaving out footer_mid.
    """
    width, height = size
    img = Image.new("P", size, WHITE)
    img.putpalette([255, 255, 255, 0, 0, 0, 200, 0, 0] + [0, 0, 0] * 253)
    draw = ImageDraw.Draw(img)
    margin = 3
    if qr:
        # The panel's white border is the code's quiet zone on the right.
        qr_left = draw_qr(draw, qr, width - 1, height, margin)
        if qr_left < width - 1:
            width, footer_mid = qr_left - 2 * margin, ""
    rows = 5  # fixed row height, so fewer lines leave space rather than grow
    footer_font = load_font(max(8, height // 11))
    footer_h = footer_font.getbbox("0:")[3] + 1
    row_h = (height - 2 * margin - footer_h) / rows
    font_px = int(row_h * 0.78)
    y = margin
    for text, colour, bold in lines[:rows]:
        font = fit_font(draw, text, font_px, bold, width - 2 * margin)
        draw.text((margin, y), text, fill=colour, font=font)
        y += row_h
    footer_colour = BLACK if footer_left == "AFT OK" else COLOUR
    draw.text((margin, height - 1), footer_left, fill=footer_colour, font=load_font(max(8, height // 11), True),
              anchor="ld")
    draw.text((width - margin, height - 1), footer_right, fill=BLACK, font=footer_font, anchor="rd")
    if footer_mid:
        draw.text((width // 2 + 8, height - 1), footer_mid, fill=BLACK, font=footer_font, anchor="md")
    return img


def screen_image(size, status, settings):
    lines, footer = build_screen(status, settings)
    hotspot = status.get("hotspot")
    qr = qr_matrix(wifi_qr_payload(hotspot["ssid"], hotspot["password"])) if hotspot else None
    return render(size, lines, footer, time.strftime("%H:%M"), status["ip"] or "", qr)


def shutdown_kind():
    """Return "reboot" or "poweroff" while the system is going down, else None."""
    _rc, state = run(["systemctl", "is-system-running"], 10)
    if state.strip() != "stopping":
        return None
    _rc, jobs = run(["systemctl", "list-jobs", "--no-legend", "--plain"], 10)
    return parse_shutdown_jobs(jobs)


def parse_shutdown_jobs(jobs):
    """Find which shutdown target systemd has queued in list-jobs output."""
    units = {line.split()[1] for line in jobs.splitlines() if len(line.split()) > 1}
    if units & {"reboot.target", "kexec.target", "soft-reboot.target"}:
        return "reboot"
    return "poweroff"


def show(display, image):
    """Send the image and wait for the panel to finish refreshing."""
    display.set_image(image)
    from inky.inky import Inky as ClassicInky
    if not isinstance(display, ClassicInky):
        display.show()
        return
    # inky 2.7's edge wait returns at once on the classic pHAT/wHAT, so it put
    # the panel into deep sleep about 17 seconds before a red refresh finished.
    # Poll the busy pin instead, then send deep sleep (command 0x10) ourselves.
    from gpiod.line import Value
    display.show(busy_wait=False)
    deadline = time.monotonic() + 45
    while display._gpio.get_value(display.busy_pin) == Value.ACTIVE and time.monotonic() < deadline:
        time.sleep(0.2)
    display._send_command(0x10, 0x01)


def get_display(settings):
    from inky.auto import auto
    display = auto()
    display.set_border(display.WHITE)
    if settings.flip:
        display.h_flip = display.v_flip = True
    return display


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="draw once and exit")
    parser.add_argument("--preview", metavar="PNG", help="render to a PNG instead of the display, then exit")
    parser.add_argument("--offline", action="store_true", help="draw the shut-down screen and exit")
    args = parser.parse_args()
    settings = Settings()

    if args.preview:
        status = collect(settings)
        screen_image((212, 104), status, settings).convert("RGB").save(args.preview)
        return 0

    display = get_display(settings)
    size = (display.width, display.height)

    def draw_offline(kind="poweroff"):
        message = "Restarting..." if kind == "reboot" else "Host shut down"
        lines = [("AFT", COLOUR, True), (message, BLACK, True)]
        show(display, render(size, lines, "AFT OFF", time.strftime("%d %b %H:%M")))

    if args.offline:
        draw_offline()
        return 0

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    last_screen = None
    last_health = None
    last_draw = 0.0
    while not stopping:
        status = collect(settings)
        lines, footer = build_screen(status, settings)
        screen = (lines, footer, status["ip"])
        # Redraw when what's shown changes, but at most once per min_redraw,
        # because each refresh flashes the panel for about 13 seconds. The
        # first draw and changes to the URL, the hotspot or AFT health skip
        # that wait.
        health = (status["ip"], status["problem"], status["hotspot"])
        urgent = health != last_health
        if screen != last_screen and (urgent or time.monotonic() - last_draw >= settings.min_redraw):
            started = time.monotonic()
            show(display, screen_image(size, status, settings))
            print(f"Drew screen in {time.monotonic() - started:.1f}s: {footer}"
                  + (f" ({status['problem']})" if status["problem"] else ""), flush=True)
            last_screen, last_health, last_draw = screen, health, time.monotonic()
        if args.once:
            break
        wait = settings.unhealthy_poll if status["problem"] else settings.poll
        deadline = time.monotonic() + wait
        while not stopping and time.monotonic() < deadline:
            time.sleep(1)
    # The panel keeps its image without power, so on shutdown or reboot replace
    # the stats with a notice. A plain service restart leaves them.
    kind = shutdown_kind() if stopping else None
    if kind:
        print(f"System {kind}: drawing notice", flush=True)
        draw_offline(kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())

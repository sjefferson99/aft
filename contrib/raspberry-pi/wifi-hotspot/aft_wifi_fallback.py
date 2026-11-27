#!/usr/bin/python3
"""Fall back to a Wi-Fi hotspot when no saved Wi-Fi network is in range (#725).

For a Pi that runs AFT away from any known network. When the Wi-Fi interface
hasn't joined a saved network for a while, this brings up a WPA2 hotspot
through NetworkManager, so clients can join it and open AFT at the hotspot
address. While the hotspot is up, it drops it now and then to look for a saved
network, because the Pi Zero 2 W's single radio can't scan reliably in access
point mode. It skips that while clients are connected.

  aft-hotspot run              the service loop (run by aft-wifi-fallback.service)
  aft-hotspot status           show the mode, the Wi-Fi state and how to join
  aft-hotspot auto|always|off  change the mode and restart the service

Modes: auto (the default) falls back to the hotspot, always keeps the hotspot
up and never joins a saved network, and off keeps it down.
Settings are read from /etc/default/aft-wifi-fallback (see the comments there).
Uses only the Python standard library, nmcli and iw.
"""

import os
import re
import signal
import subprocess
import sys
import time

CONFIG_PATH = "/etc/default/aft-wifi-fallback"
SERVICE = "aft-wifi-fallback.service"
CONNECTION = "aft-hotspot"
KEYFILE_DIR = "/etc/NetworkManager/system-connections"
MODES = ("auto", "always", "off")
# nmcli costs about 1% of a Pi Zero's CPU at this rate.
CHECK_INTERVAL = 10
NM_CONNECTED = 100
# Ambiguous characters (0/o, 1/l/i) are left out, as the password may be typed.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SSID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,30}[A-Za-z0-9._-]|[A-Za-z0-9]")
PASSWORD_RE = re.compile(r"[!-~]([ -~]{6,61})[!-~]")


class ConfigError(Exception):
    pass


def log(message):
    print(message, flush=True)


# ---- settings ----------------------------------------------------------------

def parse_config_text(text):
    """Parse KEY=VALUE lines, as systemd's EnvironmentFile and sh would."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def int_setting(values, name, default, minimum, maximum):
    raw = values.get(name, "")
    if raw == "":
        return default
    try:
        number = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number") from None
    if not minimum <= number <= maximum:
        raise ConfigError(f"{name} must be from {minimum} to {maximum}")
    return number


class Settings:
    def __init__(self, values):
        self.mode = values.get("AFT_HOTSPOT_MODE", "auto") or "auto"
        if self.mode not in MODES:
            raise ConfigError("AFT_HOTSPOT_MODE must be auto, always or off")
        self.interface = values.get("AFT_HOTSPOT_INTERFACE", "wlan0") or "wlan0"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", self.interface):
            raise ConfigError("AFT_HOTSPOT_INTERFACE isn't a valid interface name")
        self.ssid = values.get("AFT_HOTSPOT_SSID", "")
        self.password = values.get("AFT_HOTSPOT_PASSWORD", "")
        self.channel = int_setting(values, "AFT_HOTSPOT_CHANNEL", 6, 1, 13)
        self.start_wait = int_setting(values, "AFT_HOTSPOT_START_WAIT", 60, 10, 3600)
        self.rescan = int_setting(values, "AFT_HOTSPOT_RESCAN", 300, 0, 86400)
        self.connect_wait = int_setting(values, "AFT_HOTSPOT_CONNECT_WAIT", 30, 10, 300)
        if self.rescan and self.rescan < 60:
            raise ConfigError("AFT_HOTSPOT_RESCAN must be 0 (never) or at least 60")
        if self.mode != "off":
            if not SSID_RE.fullmatch(self.ssid):
                raise ConfigError(
                    "AFT_HOTSPOT_SSID must be 1 to 32 letters, digits, spaces, '.', '_' or '-', "
                    "not starting with a space")
            # WPA2 needs 8 to 63 characters. There's deliberately no way to run
            # an open network.
            if not PASSWORD_RE.fullmatch(self.password):
                raise ConfigError(
                    "AFT_HOTSPOT_PASSWORD must be 8 to 63 printable ASCII characters, "
                    "not starting or ending with a space")
            if "\\" in self.password:
                raise ConfigError("AFT_HOTSPOT_PASSWORD can't contain a backslash")


def load_settings(path=CONFIG_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return Settings(parse_config_text(f.read()))
    except OSError as e:
        raise ConfigError(f"Can't read {path}: {e.strerror}") from None


def new_password():
    import secrets  # only needed at install, so the service stays smaller
    return "-".join("".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4)) for _ in range(3))


def default_ssid():
    import socket
    host = re.sub(r"[^A-Za-z0-9._-]", "", socket.gethostname().split(".")[0].lower())
    return f"AFT-{host}"[:32].rstrip(" ")


def write_private(path, text):
    """Write a root-only file atomically, so readers never see half of it."""
    import tempfile
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".aft-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def new_config(template_path, dest):
    """Create the settings file from the template with a new SSID and password."""
    with open(template_path, encoding="utf-8") as f:
        text = f.read()
    text = text.replace("@SSID@", default_ssid()).replace("@PASSWORD@", new_password())
    write_private(dest, text)


def set_mode_in_text(text, mode):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"\s*AFT_HOTSPOT_MODE\s*=", line):
            lines[i] = f"AFT_HOTSPOT_MODE={mode}"
            break
    else:
        lines.append(f"AFT_HOTSPOT_MODE={mode}")
    return "\n".join(lines) + "\n"


# ---- NetworkManager ----------------------------------------------------------

def run(cmd, timeout=60):
    """Run a command, returning (returncode, stdout). Never raises."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout
    except (OSError, subprocess.SubprocessError):
        return None, ""


def keyfile_text(settings, connection_uuid):
    """NetworkManager keyfile for the hotspot. WPA2 (RSN, CCMP) only.

    autoconnect is off, so NetworkManager never picks the hotspot over a saved
    network by itself. Management frame protection is off because the Pi's
    brcmfmac firmware fails to start an access point with it.
    """
    return (
        "# Written by aft-wifi-fallback from /etc/default/aft-wifi-fallback.\n"
        "# Edit that file instead: this one is replaced when the service starts.\n"
        "[connection]\n"
        f"id={CONNECTION}\n"
        f"uuid={connection_uuid}\n"
        "type=wifi\n"
        f"interface-name={settings.interface}\n"
        "autoconnect=false\n"
        "\n"
        "[wifi]\n"
        "mode=ap\n"
        f"ssid={settings.ssid}\n"
        "band=bg\n"
        f"channel={settings.channel}\n"
        "\n"
        "[wifi-security]\n"
        "key-mgmt=wpa-psk\n"
        "proto=rsn;\n"
        "pairwise=ccmp;\n"
        "group=ccmp;\n"
        "pmf=1\n"
        f"psk={settings.password}\n"
        "\n"
        "[ipv4]\n"
        "method=shared\n"
        "address1=10.42.0.1/24\n"
        "\n"
        "[ipv6]\n"
        "method=disabled\n"
    )


def existing_uuid(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("uuid="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def ensure_profile(settings, keyfile_dir=KEYFILE_DIR):
    """Write the hotspot profile if it differs from the settings and load it.

    The keyfile is written directly, rather than through nmcli, so the
    password never appears on a command line. Returns True if it changed.
    """
    import uuid
    path = os.path.join(keyfile_dir, f"{CONNECTION}.nmconnection")
    text = keyfile_text(settings, existing_uuid(path) or str(uuid.uuid4()))
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    write_private(path, text)
    rc, _out = run(["nmcli", "connection", "load", path])
    if rc != 0:
        raise RuntimeError("NetworkManager didn't load the hotspot profile")
    return True


def nm_fields(out):
    """Parse nmcli -t -e no -f output into {field: value}.

    Keyed rather than positional (-g), because nmcli leaves out fields that
    have no value, such as the state of an inactive connection.
    """
    fields = {}
    for line in out.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields.setdefault(key, value)
    return fields


def device_state(interface):
    """Return (state number, active connection name) for the interface."""
    rc, out = run(["nmcli", "-t", "-e", "no", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", interface], 15)
    if rc != 0:
        return 0, ""
    fields = nm_fields(out)
    match = re.match(r"\d+", fields.get("GENERAL.STATE", ""))
    return (int(match.group()) if match else 0), fields.get("GENERAL.CONNECTION", "").strip()


def wifi_state(interface):
    """Return "hotspot", "client" (joined a saved network) or "none"."""
    state, connection = device_state(interface)
    if connection == CONNECTION:
        return "hotspot"
    if state == NM_CONNECTED and connection:
        return "client"
    return "none"


def hotspot_clients(interface):
    """Number of stations joined to the hotspot. 0 if iw can't tell."""
    rc, out = run(["iw", "dev", interface, "station", "dump"], 15)
    if rc != 0:
        return 0
    return sum(1 for line in out.splitlines() if line.startswith("Station "))


def hotspot_up(settings):
    rc, _out = run(["nmcli", "--wait", "45", "connection", "up", "id", CONNECTION, "ifname", settings.interface], 60)
    return rc == 0


def hotspot_down():
    run(["nmcli", "--wait", "30", "connection", "down", "id", CONNECTION], 45)


def saved_networks():
    """Saved Wi-Fi client profiles as dicts, highest autoconnect priority first."""
    rc, out = run(["nmcli", "-e", "no", "-g", "UUID,TYPE", "connection", "show"], 15)
    if rc != 0:
        return []
    networks = []
    for line in out.splitlines():
        conn_uuid, _sep, conn_type = line.partition(":")
        if conn_type != "802-11-wireless":
            continue
        fields = ("connection.id,802-11-wireless.ssid,802-11-wireless.mode,"
                  "802-11-wireless.hidden,connection.autoconnect,connection.autoconnect-priority")
        rc, detail = run(["nmcli", "-t", "-e", "no", "-f", fields, "connection", "show", "uuid", conn_uuid], 15)
        values = nm_fields(detail)
        name = values.get("connection.id", "")
        ssid = values.get("802-11-wireless.ssid", "")
        mode = values.get("802-11-wireless.mode", "")
        hidden = values.get("802-11-wireless.hidden", "")
        priority = values.get("connection.autoconnect-priority", "")
        if rc != 0 or not name:
            continue
        if name == CONNECTION or mode not in ("", "infrastructure") or values.get("connection.autoconnect") != "yes":
            continue
        try:
            prio = int(priority)
        except ValueError:
            prio = 0
        networks.append({"uuid": conn_uuid, "name": name, "ssid": ssid, "hidden": hidden == "yes", "priority": prio})
    networks.sort(key=lambda n: -n["priority"])
    return networks


def visible_ssids(interface):
    """SSIDs in range. Scans first; the radio needs a moment after AP mode."""
    for _attempt in range(3):
        rc, _out = run(["nmcli", "device", "wifi", "rescan", "ifname", interface], 30)
        if rc == 0:
            break
        time.sleep(3)
    time.sleep(5)
    rc, out = run(["nmcli", "-e", "no", "-g", "SSID", "device", "wifi", "list", "ifname", interface, "--rescan", "no"], 30)
    return {line for line in out.splitlines() if line} if rc == 0 else set()


def scan_candidates(networks, visible):
    """Saved networks worth trying: those in range, then hidden ones."""
    in_range = [n for n in networks if n["ssid"] in visible]
    hidden = [n for n in networks if n["hidden"] and n not in in_range]
    return in_range + hidden


def try_saved_networks(settings):
    """Drop the hotspot and try to join a saved network. True if joined."""
    log("Looking for a saved Wi-Fi network")
    hotspot_down()
    visible = visible_ssids(settings.interface)
    if wifi_state(settings.interface) == "client":
        return True
    for network in scan_candidates(saved_networks(), visible):
        log(f"Trying saved network {network['name']}")
        rc, _out = run(["nmcli", "--wait", str(settings.connect_wait), "connection", "up", "uuid", network["uuid"],
                        "ifname", settings.interface], settings.connect_wait + 15)
        if rc == 0 and wifi_state(settings.interface) == "client":
            return True
    return wifi_state(settings.interface) == "client"


# ---- service loop ------------------------------------------------------------

class Fallback:
    """The auto-mode state machine, kept apart from the loop so it can be tested."""

    def __init__(self, settings, now, hotspot_active=False):
        self.settings = settings
        # Counting from start gives saved networks start_wait to join at boot.
        self.disconnected_since = now
        self.hotspot_since = None
        self.retry_at = 0.0
        # A hotspot that was already up, such as after switching from always
        # to auto, looks for a saved network on the first check rather than a
        # whole interval later. The look still waits while clients are joined.
        if hotspot_active and settings.rescan:
            self.hotspot_since = now - settings.rescan

    def step(self, now, state, clients=lambda: 0):
        """Act on the current Wi-Fi state. Returns the action taken, for tests and logs."""
        if state == "client":
            self.disconnected_since = None
            self.hotspot_since = None
            return None
        if state == "hotspot":
            self.disconnected_since = None
            if self.hotspot_since is None:
                self.hotspot_since = now
            if not self.settings.rescan or now - self.hotspot_since < self.settings.rescan:
                return None
            if clients():
                return None
            return "rescan"
        self.hotspot_since = None
        if self.disconnected_since is None:
            self.disconnected_since = now
        if now - self.disconnected_since >= self.settings.start_wait and now >= self.retry_at:
            return "hotspot"
        return None


def serve(settings, stopping):
    if settings.mode == "off":
        if wifi_state(settings.interface) == "hotspot":
            log("Mode is off: taking the hotspot down")
            hotspot_down()
        log("Mode is off: nothing to do")
        return 0

    changed = ensure_profile(settings)
    state = wifi_state(settings.interface)
    if changed and state == "hotspot":
        log("Hotspot settings changed: restarting the hotspot")
        hotspot_up(settings)
    log(f"Mode {settings.mode}, interface {settings.interface}, hotspot {settings.ssid!r} on channel {settings.channel}")

    fallback = Fallback(settings, time.monotonic(), hotspot_active=state == "hotspot")
    while not stopping():
        state = wifi_state(settings.interface)
        now = time.monotonic()
        if settings.mode == "always":
            action = "hotspot" if state != "hotspot" and now >= fallback.retry_at else None
        else:
            action = fallback.step(now, state, lambda: hotspot_clients(settings.interface))
        if action == "rescan":
            if try_saved_networks(settings):
                log("Joined a saved network")
                fallback.step(time.monotonic(), "client")
                continue
            log("No saved network found")
            action = "hotspot"
        if action == "hotspot":
            log("Starting the hotspot" if settings.mode == "always" else "No saved Wi-Fi network: starting the hotspot")
            if hotspot_up(settings):
                fallback.hotspot_since = time.monotonic()
            else:
                log("The hotspot didn't start; trying again in a minute")
                fallback.retry_at = time.monotonic() + 60
        deadline = time.monotonic() + CHECK_INTERVAL
        while not stopping() and time.monotonic() < deadline:
            time.sleep(1)
    return 0


# ---- commands ----------------------------------------------------------------

def cmd_run():
    stop = {"flag": False}

    def handler(_signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    try:
        settings = load_settings()
    except ConfigError as e:
        log(f"Not starting: {e}")
        return 1
    try:
        return serve(settings, lambda: stop["flag"])
    except RuntimeError as e:
        log(f"Stopping: {e}")
        return 1


def cmd_status():
    try:
        settings = load_settings()
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 1
    state, connection = device_state(settings.interface)
    print(f"Mode:      {settings.mode}")
    if connection == CONNECTION:
        clients = hotspot_clients(settings.interface)
        print(f"Wi-Fi:     hotspot up, {clients} client{'' if clients == 1 else 's'} connected")
    elif state == NM_CONNECTED and connection:
        print(f"Wi-Fi:     joined {connection}")
    else:
        print("Wi-Fi:     not connected")
    if settings.mode != "off":
        print(f"Hotspot:   {settings.ssid}")
        print(f"Password:  {settings.password}")
        print("AFT:       https://10.42.0.1/ while the hotspot is up")
    return 0


def cmd_set_mode(mode):
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"Can't read {CONFIG_PATH}: {e.strerror}", file=sys.stderr)
        return 1
    text = set_mode_in_text(text, mode)
    try:
        Settings(parse_config_text(text))
    except ConfigError as e:
        print(f"Fix {CONFIG_PATH} first: {e}", file=sys.stderr)
        return 1
    write_private(CONFIG_PATH, text)
    rc, _out = run(["systemctl", "restart", SERVICE])
    if rc != 0:
        print(f"Saved, but restarting {SERVICE} failed. Check: systemctl status {SERVICE}", file=sys.stderr)
        return 1
    notes = {
        "auto": "Falls back to the hotspot when no saved network is in range.",
        "always": "The hotspot is starting. The Pi leaves any saved network it had joined.",
        "off": "The hotspot is off and won't start.",
    }
    print(f"Mode set to {mode}. {notes[mode]}")
    return 0


def main(argv):
    command = argv[1] if len(argv) > 1 else ""
    if command in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if command == "new-config" and len(argv) == 4:
        new_config(argv[2], argv[3])
        return 0
    if os.geteuid() != 0:
        print("Run with sudo", file=sys.stderr)
        return 1
    if command == "run":
        return cmd_run()
    if command in ("status", ""):
        return cmd_status()
    if command in MODES:
        return cmd_set_mode(command)
    print("Usage: aft-hotspot [status | auto | always | off]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

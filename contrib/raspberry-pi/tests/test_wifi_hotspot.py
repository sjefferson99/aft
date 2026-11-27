"""Unit tests for the Pi Wi-Fi hotspot fallback (#725).

They need no Pi, NetworkManager or display. Run from the repo root:

    .venv/bin/python -m pytest -q contrib/raspberry-pi/tests
"""

import importlib.util
import os
import stat
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fallback = load("aft_wifi_fallback", "wifi-hotspot/aft_wifi_fallback.py")

GOOD = {"AFT_HOTSPOT_SSID": "AFT-aft-portable", "AFT_HOTSPOT_PASSWORD": "abcd-efgh-jkmn"}


def settings(**overrides):
    return fallback.Settings({**GOOD, **overrides})


# ---- settings ----------------------------------------------------------------

def test_template_parses_once_filled_in():
    with open(os.path.join(HERE, "..", "wifi-hotspot", "aft-wifi-fallback.env")) as f:
        text = f.read().replace("@SSID@", "AFT-test").replace("@PASSWORD@", fallback.new_password())
    s = fallback.Settings(fallback.parse_config_text(text))
    assert (s.mode, s.channel, s.start_wait, s.rescan, s.interface) == ("auto", 6, 60, 300, "wlan0")


def test_parse_strips_quotes_and_comments():
    values = fallback.parse_config_text('# c\nA="x y"\nB=\'z\'\n\nC = 1\nnot a setting\n')
    assert values == {"A": "x y", "B": "z", "C": "1"}


@pytest.mark.parametrize("password", ["", "short", "x" * 64, " leading-space", "trailing-space ", "back\\slash",
                                      "non-ascii-é-pass"])
def test_rejects_bad_passwords(password):
    with pytest.raises(fallback.ConfigError):
        settings(AFT_HOTSPOT_PASSWORD=password)


@pytest.mark.parametrize("password", ["12345678", "x" * 63, "with space;and#marks!"])
def test_accepts_wpa2_passwords(password):
    assert settings(AFT_HOTSPOT_PASSWORD=password).password == password


@pytest.mark.parametrize("ssid", ["", " lead", "x" * 33, "semi;colon", "new\nline", "trail "])
def test_rejects_bad_ssids(ssid):
    with pytest.raises(fallback.ConfigError):
        settings(AFT_HOTSPOT_SSID=ssid)


@pytest.mark.parametrize("name,value", [
    ("AFT_HOTSPOT_MODE", "on"), ("AFT_HOTSPOT_CHANNEL", "14"), ("AFT_HOTSPOT_CHANNEL", "six"),
    ("AFT_HOTSPOT_RESCAN", "30"), ("AFT_HOTSPOT_START_WAIT", "5"), ("AFT_HOTSPOT_INTERFACE", "wlan0; rm"),
])
def test_rejects_bad_values(name, value):
    with pytest.raises(fallback.ConfigError):
        settings(**{name: value})


def test_off_mode_needs_no_password():
    assert fallback.Settings({"AFT_HOTSPOT_MODE": "off"}).mode == "off"


def test_rescan_zero_means_never():
    assert settings(AFT_HOTSPOT_RESCAN="0").rescan == 0


def test_new_password_is_random_and_valid():
    passwords = {fallback.new_password() for _ in range(50)}
    assert len(passwords) == 50
    for password in passwords:
        assert settings(AFT_HOTSPOT_PASSWORD=password)
        assert len(password) == 14


def test_new_config_is_root_only(tmp_path):
    dest = tmp_path / "settings"
    fallback.new_config(os.path.join(HERE, "..", "wifi-hotspot", "aft-wifi-fallback.env"), str(dest))
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    s = fallback.Settings(fallback.parse_config_text(dest.read_text()))
    assert s.ssid.startswith("AFT-")


def test_set_mode_replaces_or_appends():
    assert "AFT_HOTSPOT_MODE=always\n" in fallback.set_mode_in_text("X=1\nAFT_HOTSPOT_MODE=auto\nY=2", "always")
    assert fallback.set_mode_in_text("X=1\n", "off").endswith("AFT_HOTSPOT_MODE=off\n")


# ---- profile ----------------------------------------------------------------

def test_keyfile_is_wpa2_only_and_never_autoconnects():
    text = fallback.keyfile_text(settings(AFT_HOTSPOT_CHANNEL="11"), "u-1")
    for line in ("autoconnect=false", "mode=ap", "channel=11", "key-mgmt=wpa-psk", "proto=rsn;",
                 "pairwise=ccmp;", "psk=abcd-efgh-jkmn", "method=shared", "address1=10.42.0.1/24"):
        assert line in text.splitlines()
    assert "wpa;" not in text and "tkip" not in text


def test_ensure_profile_writes_once_and_keeps_uuid(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fallback, "run", lambda cmd, timeout=60: calls.append(cmd) or (0, ""))
    assert fallback.ensure_profile(settings(), str(tmp_path)) is True
    path = tmp_path / "aft-hotspot.nmconnection"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    first_uuid = fallback.existing_uuid(str(path))
    assert fallback.ensure_profile(settings(), str(tmp_path)) is False
    assert fallback.ensure_profile(settings(AFT_HOTSPOT_PASSWORD="new-password"), str(tmp_path)) is True
    assert fallback.existing_uuid(str(path)) == first_uuid
    assert [c[:3] for c in calls] == [["nmcli", "connection", "load"]] * 2
    # The password goes into the file, never onto a command line.
    assert not any("abcd-efgh-jkmn" in " ".join(c) for c in calls)


# ---- NetworkManager parsing -------------------------------------------------

@pytest.mark.parametrize("out,expected", [
    ("GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Home: Wi-Fi\n", "client"),
    ("GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:aft-hotspot\n", "hotspot"),
    ("GENERAL.STATE:30 (disconnected)\nGENERAL.CONNECTION:\n", "none"),
    ("GENERAL.STATE:70 (connecting (getting IP configuration))\nGENERAL.CONNECTION:Home\n", "none"),
])
def test_wifi_state(monkeypatch, out, expected):
    monkeypatch.setattr(fallback, "run", lambda cmd, timeout=60: (0, out))
    assert fallback.wifi_state("wlan0") == expected


def test_wifi_state_when_nmcli_fails(monkeypatch):
    monkeypatch.setattr(fallback, "run", lambda cmd, timeout=60: (None, ""))
    assert fallback.wifi_state("wlan0") == "none"


def test_hotspot_clients(monkeypatch):
    dump = "Station aa:bb:cc:dd:ee:01 (on wlan0)\n\tinactive time:\t10 ms\nStation aa:bb:cc:dd:ee:02 (on wlan0)\n"
    monkeypatch.setattr(fallback, "run", lambda cmd, timeout=60: (0, dump))
    assert fallback.hotspot_clients("wlan0") == 2


def test_saved_networks_skips_hotspot_and_manual_profiles(monkeypatch):
    keys = ("connection.id", "802-11-wireless.ssid", "802-11-wireless.mode", "802-11-wireless.hidden",
            "connection.autoconnect", "connection.autoconnect-priority")

    def detail(*values):
        # nmcli leaves out empty fields, as for u3's mode.
        return "".join(f"{k}:{v}\n" for k, v in zip(keys, values) if v != "")

    details = {
        "u1": detail("Home", "Home SSID", "infrastructure", "no", "yes", "0"),
        "u2": detail("aft-hotspot", "AFT-x", "ap", "no", "no", "0"),
        "u3": detail("Office: 2", "Office: main", "", "no", "yes", "10"),
        "u4": detail("Manual", "Manual", "infrastructure", "no", "no", "0"),
        "u5": detail("Hidden", "Secret", "infrastructure", "yes", "yes", "-5"),
    }

    def run(cmd, timeout=60):
        if cmd[-1] == "show":
            return 0, "u1:802-11-wireless\nu2:802-11-wireless\nu3:802-11-wireless\nu6:802-3-ethernet\n" \
                      "u4:802-11-wireless\nu5:802-11-wireless\n"
        return 0, details[cmd[-1]]

    monkeypatch.setattr(fallback, "run", run)
    networks = fallback.saved_networks()
    assert [n["name"] for n in networks] == ["Office: 2", "Home", "Hidden"]
    assert networks[0]["ssid"] == "Office: main"
    candidates = fallback.scan_candidates(networks, {"Home SSID", "Neighbour"})
    assert [n["name"] for n in candidates] == ["Home", "Hidden"]


# ---- auto-mode state machine -------------------------------------------------

def test_waits_at_boot_for_a_saved_network():
    f = fallback.Fallback(settings(), now=0)
    assert f.step(30, "none") is None
    assert f.step(59, "none") is None
    assert f.step(60, "none") == "hotspot"


def test_joining_at_boot_means_no_hotspot():
    f = fallback.Fallback(settings(), now=0)
    assert f.step(20, "client") is None
    assert f.step(100, "client") is None


def test_losing_a_network_waits_before_the_hotspot():
    f = fallback.Fallback(settings(), now=0)
    f.step(10, "client")
    assert f.step(500, "none") is None
    assert f.step(559, "none") is None
    assert f.step(560, "none") == "hotspot"


def test_rescans_after_the_interval_unless_clients_are_connected():
    f = fallback.Fallback(settings(AFT_HOTSPOT_RESCAN="300"), now=0)
    f.step(60, "none")
    f.hotspot_since = 60
    assert f.step(359, "hotspot") is None
    assert f.step(360, "hotspot", clients=lambda: 1) is None
    assert f.step(400, "hotspot", clients=lambda: 0) == "rescan"


def test_never_rescans_with_zero():
    f = fallback.Fallback(settings(AFT_HOTSPOT_RESCAN="0"), now=0)
    f.step(0, "hotspot")
    assert f.step(10 ** 6, "hotspot") is None


def test_failed_start_waits_for_retry():
    f = fallback.Fallback(settings(), now=0)
    f.retry_at = 120
    assert f.step(60, "none") is None
    assert f.step(120, "none") == "hotspot"


# ---- Inky display ------------------------------------------------------------

@pytest.fixture
def inky():
    pytest.importorskip("PIL")
    sys.modules.pop("aft_inky_status", None)
    return load("aft_inky_status", "inky-status/aft_inky_status.py")


def test_inky_parses_an_active_hotspot(inky):
    out = ("GENERAL.STATE:activated\n802-11-wireless.ssid:AFT-aft-portable\n"
           "802-11-wireless-security.psk:abcd-efgh-jkmn\nIP4.ADDRESS[1]:10.42.0.1/24\n")
    assert inky.parse_hotspot(out) == {"ssid": "AFT-aft-portable", "password": "abcd-efgh-jkmn",
                                       "address": "10.42.0.1"}


@pytest.mark.parametrize("out", [
    "",
    # Inactive: nmcli leaves out the state and address.
    "802-11-wireless.ssid:AFT-x\n802-11-wireless-security.psk:pw\n",
    "GENERAL.STATE:activating\n802-11-wireless.ssid:AFT-x\n802-11-wireless-security.psk:pw\n",
])
def test_inky_ignores_an_inactive_hotspot(inky, out):
    assert inky.parse_hotspot(out) is None


def test_inky_qr_payload_escapes_special_characters(inky):
    assert inky.wifi_qr_payload("My;Net", 'p:a,s"s\\') == 'WIFI:T:WPA;S:My\\;Net;P:p\\:a\\,s\\"s\\\\;;'


def test_inky_hotspot_screen(inky, monkeypatch):
    monkeypatch.setenv("AFT_URL_HOST", "aft-portable")
    status = {"ip": "10.42.0.1", "problem": None, "load": (0.5, 0.4, 0.3), "mem_used": 1, "mem_total": 2,
              "swap_used": 0, "swap_total": 0, "aft": (2, 30, 1, 4),
              "hotspot": {"ssid": "AFT-aft-portable", "password": "abcd-efgh-jkmn", "address": "10.42.0.1"}}
    lines, footer = inky.build_screen(status, inky.Settings())
    texts = [text for text, _colour, _bold in lines]
    assert texts[:4] == ["Join Wi-Fi", "AFT-aft-portable", "abcd-efgh-jkmn", "https://10.42.0.1/"]
    assert footer == "AFT OK"
    image = inky.screen_image((212, 104), status, inky.Settings())
    assert image.size == (212, 104)

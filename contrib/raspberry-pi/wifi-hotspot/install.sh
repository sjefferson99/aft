#!/bin/sh
# Install the AFT Wi-Fi hotspot fallback (#725) as a systemd service.
# Run from this directory: sudo ./install.sh
set -eu

PREFIX=/opt/aft-wifi-fallback
SETTINGS=/etc/default/aft-wifi-fallback
HERE=$(cd "$(dirname "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./install.sh" >&2
    exit 1
fi
if ! command -v nmcli >/dev/null || ! systemctl is-active --quiet NetworkManager; then
    echo "NetworkManager isn't running. This needs Raspberry Pi OS bookworm or later." >&2
    exit 1
fi

echo "Installing packages..."
apt-get install -y -q iw

install -d -m 755 "$PREFIX"
install -m 755 "$HERE/aft_wifi_fallback.py" "$PREFIX/"
ln -sf "$PREFIX/aft_wifi_fallback.py" /usr/local/sbin/aft-hotspot
install -m 644 "$HERE/aft-wifi-fallback.service" /etc/systemd/system/

if [ ! -e "$SETTINGS" ]; then
    python3 "$PREFIX/aft_wifi_fallback.py" new-config "$HERE/aft-wifi-fallback.env" "$SETTINGS"
    echo "Created $SETTINGS with a new hotspot password"
else
    echo "Keeping existing $SETTINGS"
fi

if ! iw reg get 2>/dev/null | grep -q '^country [A-Z][A-Z]'; then
    echo "Warning: no Wi-Fi country is set, so the hotspot may not start." >&2
    echo "Set it with: sudo raspi-config nonint do_wifi_country GB  (use your country code)" >&2
fi

systemctl daemon-reload
systemctl enable aft-wifi-fallback.service
systemctl restart aft-wifi-fallback.service

echo
aft-hotspot status
echo
echo "Add https://10.42.0.1 to CORS_ALLOWED_ORIGINS in AFT's .env (see README.md)."

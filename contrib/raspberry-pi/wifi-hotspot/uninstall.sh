#!/bin/sh
# Remove the AFT Wi-Fi hotspot fallback. Run: sudo ./uninstall.sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./uninstall.sh" >&2
    exit 1
fi

systemctl disable --now aft-wifi-fallback.service 2>/dev/null || true
# Taking the hotspot down lets NetworkManager join a saved network again.
nmcli connection delete id aft-hotspot 2>/dev/null || true
rm -f /etc/systemd/system/aft-wifi-fallback.service \
      /etc/NetworkManager/system-connections/aft-hotspot.nmconnection \
      /usr/local/sbin/aft-hotspot \
      /etc/default/aft-wifi-fallback
rm -rf /opt/aft-wifi-fallback
systemctl daemon-reload
echo "Removed."

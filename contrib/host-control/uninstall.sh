#!/bin/sh
# Remove the AFT host restart and shut down service. Run: sudo ./uninstall.sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./uninstall.sh" >&2
    exit 1
fi

systemctl disable --now aft-host-control.path aft-host-control-clear.service 2>/dev/null || true
rm -f /etc/systemd/system/aft-host-control.path \
      /etc/systemd/system/aft-host-control.service \
      /etc/systemd/system/aft-host-control-clear.service \
      /usr/local/libexec/aft-host-control \
      /etc/default/aft-host-control
systemctl daemon-reload
echo "Removed. Also set HOST_POWER_CONTROL=false and remove the host-control mount."

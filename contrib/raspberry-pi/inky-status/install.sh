#!/bin/sh
# Install the AFT Inky pHAT status display as a systemd service.
# Run from this directory: sudo ./install.sh
set -eu

PREFIX=/opt/aft-inky-status
CONFIG=/boot/firmware/config.txt
HERE=$(cd "$(dirname "$0")" && pwd)
REBOOT=0

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./install.sh" >&2
    exit 1
fi

echo "Installing packages..."
apt-get install -y -q python3-venv python3-pil python3-numpy python3-spidev \
    python3-smbus2 python3-libgpiod python3-qrcode fonts-dejavu-core

# The display uses SPI, and I2C to read its EEPROM. The inky library drives
# chip select itself, so the kernel must not claim CE0 (spi0-0cs).
if ! grep -q '^dtparam=spi=on' "$CONFIG" || ! grep -q '^dtparam=i2c_arm=on' "$CONFIG"; then
    raspi-config nonint do_spi 0
    raspi-config nonint do_i2c 0
    REBOOT=1
fi
if ! grep -q '^dtoverlay=spi0-0cs' "$CONFIG"; then
    cp "$CONFIG" "$CONFIG.bak-aft-inky"
    printf '\n[all]\ndtoverlay=spi0-0cs\n' >> "$CONFIG"
    REBOOT=1
fi

echo "Creating $PREFIX/venv..."
mkdir -p "$PREFIX"
# System site packages reuse the apt numpy, Pillow and gpiod builds, which
# would take a long time to build with pip on a Pi Zero.
[ -x "$PREFIX/venv/bin/python" ] || python3 -m venv --system-site-packages "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q 'inky>=2.7,<3'

install -m 755 "$HERE/aft_inky_status.py" "$PREFIX/"
install -m 644 "$HERE/aft-inky-status.service" /etc/systemd/system/
if [ ! -e /etc/default/aft-inky-status ]; then
    install -m 644 "$HERE/aft-inky-status.env" /etc/default/aft-inky-status
else
    echo "Keeping existing /etc/default/aft-inky-status"
fi

systemctl daemon-reload
systemctl enable aft-inky-status.service

if [ "$REBOOT" -eq 1 ]; then
    echo "SPI/I2C settings changed. Reboot to start the display: sudo reboot"
else
    systemctl restart aft-inky-status.service
    echo "Started. Check it with: systemctl status aft-inky-status"
fi

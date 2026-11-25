#!/bin/sh
# Install the AFT host restart and shut down service (#726).
# Only for hosts dedicated to AFT: it lets AFT administrators power the whole
# host off. Run from this directory:
#
#   sudo ./install.sh /path/to/aft/host-control
#
# The folder is the one mounted into the server container as
# /app/host-control. AFT_UID sets its owner, the server container's user
# (1000 in AFT's images).
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
AFT_UID=${AFT_UID:-1000}

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./install.sh /path/to/aft/host-control" >&2
    exit 1
fi
if [ $# -ne 1 ]; then
    echo "Usage: sudo ./install.sh /path/to/aft/host-control" >&2
    exit 1
fi

DIR=$1
case "$DIR" in
    /*) ;;
    *) echo "Give the folder as an absolute path" >&2; exit 1 ;;
esac
# The path goes into systemd units, so keep it to characters they don't treat
# specially.
case "$DIR" in
    *[!A-Za-z0-9/._-]*) echo "The folder path can only use letters, digits, / . _ and -" >&2; exit 1 ;;
esac
DIR=${DIR%/}

echo "Preparing $DIR..."
mkdir -p "$DIR"
chown "$AFT_UID:$AFT_UID" "$DIR"
chmod 700 "$DIR"
# A request written before the service existed must not act at once.
rm -f -- "$DIR/request"

install -d -m 755 /usr/local/libexec
install -m 755 "$HERE/aft-host-control" /usr/local/libexec/aft-host-control
printf 'AFT_HOST_CONTROL_DIR=%s\n' "$DIR" > /etc/default/aft-host-control
chmod 644 /etc/default/aft-host-control
for unit in aft-host-control.path aft-host-control.service aft-host-control-clear.service; do
    sed "s|@HOST_CONTROL_DIR@|$DIR|g" "$HERE/$unit" > "/etc/systemd/system/$unit"
    chmod 644 "/etc/systemd/system/$unit"
done

systemctl daemon-reload
systemctl enable --now aft-host-control-clear.service aft-host-control.path

echo "Installed. Check it with: systemctl status aft-host-control.path"
echo "Then mount $DIR into the server container as /app/host-control and set"
echo "HOST_POWER_CONTROL=true in .env (see README.md)."

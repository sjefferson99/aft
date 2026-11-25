# AFT on a Raspberry Pi Zero 2 W

AFT can run on a Raspberry Pi Zero 2 W (512 MB RAM) for a small team or a portable demo. The Pi needs the OS and AFT tuning below to fit in memory. This folder holds the example files, and an optional status display for a Pimoroni Inky pHAT.

Tested with AFT v2026.11.2 on 64-bit Raspberry Pi OS Lite (Debian 13 trixie, kernel 6.18), headless, with Docker Engine 29. Tracked in [#723](https://github.com/sjefferson99/aft/issues/723).

| File | What it is |
|---|---|
| [`env.pi-zero-2w`](env.pi-zero-2w) | The `.env` values to change from `.env.example` |
| [`compose.override.yaml`](compose.override.yaml) | Gives the server time to start on a cold boot |
| [`inky-status/`](inky-status/) | Optional Inky pHAT status display, installed as a systemd service |

**What to expect:** at idle, the whole system uses about 265 MB of the 462 MB the OS sees, with about 260 MB more in swap. Most of that swap is zram, which compresses about 200 MB down to about 40 MB of RAM. The stack is healthy about two minutes after power on. Pages are usable for one or two people, and slower than on a bigger machine.

**Requirements:**
- A 64-bit OS. AFT's images are `amd64` and `arm64` only, and the MySQL image has no 32-bit ARM build.
- A good A1/A2-rated SD card. Swap and MySQL both use it.

## 1. Operating system

Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager, and set the hostname, user, Wi-Fi and SSH there. No desktop is needed: the Pi runs headless and clients use a browser on another device.

### Boot config

In `/boot/firmware/config.txt`, give the GPU as little memory as possible and turn off unused hardware. Under `[all]`:

```ini
gpu_mem=16
```

Then change these existing lines:

```ini
dtparam=audio=off
camera_auto_detect=0
```

With `gpu_mem=16`, `vcgencmd get_mem arm` reports `arm=496M`.

### Swap

Raspberry Pi OS already sets up a zram swap device through `rpi-swap` (zstd, the size of RAM, priority 100). Keep it, and add a 512 MB swap file at a lower priority, so the SD card is only used once zram is full:

```sh
sudo fallocate -l 512M /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon --priority 10 /swapfile
echo '/swapfile none swap sw,pri=10 0 0' | sudo tee -a /etc/fstab
```

Check both are in use with `sudo swapon --show`. The kernel settings (`vm.swappiness=60`, `vm.page-cluster=0`) are left at the distribution defaults.

### Background services

Turn off services that take memory or CPU and aren't needed:

```sh
sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer bluetooth
```

With the apt timers off, the Pi doesn't update itself. Run `sudo apt update && sudo apt upgrade` yourself from time to time.

### Optional: per-container memory figures

The Raspberry Pi kernel turns off the memory cgroup, so `docker stats` shows `0B` for every container. To see per-container memory, add ` cgroup_enable=memory` to the end of the single line in `/boot/firmware/cmdline.txt` and reboot. This costs a little memory, so you only need it while you're measuring.

## 2. AFT

Install Docker Engine and the compose plugin, then follow the [quick start](https://github.com/sjefferson99/aft#quick-start) with these changes:

1. **`.env`:** start from `.env.example`, then set the values in [`env.pi-zero-2w`](env.pi-zero-2w). The values are explained in [Database memory tuning](../../www/docs/administration.md#database-memory-tuning) and [Server workers and threads](../../www/docs/administration.md#server-workers-and-threads).
2. **`compose.override.yaml`:** copy [`compose.override.yaml`](compose.override.yaml) next to `compose.yml`. Without it, the server's healthcheck can time out on a cold boot, and nginx never starts.
3. **Origins:** add every address clients type into the browser to `CORS_ALLOWED_ORIGINS`, for example `https://aft-portable` and the Pi's IP address. Sign-in and live updates fail from any address that isn't listed.

The web container creates a self-signed certificate the first time it starts, so HTTPS works straight away. Browsers will warn about the certificate until you replace it with a real one (see [HTTPS and Session Cookie Security](../../www/docs/administration.md#https-and-session-cookie-security)).

**Gunicorn threads:** each open AFT tab holds one server thread for as long as it stays open, whether or not it's signed in. Once every thread is held, every request hangs until a tab closes. On the Pi, 8 threads served 7 open tabs, and holding them open cost about 2 MB more than 2 threads did. With 2 threads, two open tabs hung the server. Set `GUNICORN_THREADS` to at least 8, and raise it if more tabs will be open at once. Raise threads rather than workers: each extra worker costs about 80 MB.

The first `docker compose pull` and start are slow on a Pi Zero, so allow several minutes.

## 3. Optional: Inky pHAT status display

[`inky-status/`](inky-status/) shows the host's status on a [Pimoroni Inky pHAT](https://shop.pimoroni.com/products/inky-phat) e-ink display:

- the URL clients connect to (`https://<hostname>/`), with the IP address at the bottom for clients that can't resolve the name
- AFT health: `AFT OK`, or the first problem in red, such as `Starting: server`, `Down: db`, `Web not responding`, `DB query failed` or `No Wi-Fi`
- load average, and memory and swap use
- non-archived boards and cards, users who signed in in the last 24 hours, and cards edited in the last 24 hours

The counts come from read-only queries run inside the `aft-db` container with the database credentials already in that container. The display needs no AFT account and no server changes. "Signed in" uses each user's last sign-in time, so someone still working in an earlier session isn't counted.

### Install

Copy the `inky-status` folder to the Pi, then run:

```sh
cd inky-status
sudo ./install.sh
```

The installer:
- installs the Python packages from apt
- turns on SPI and I2C, with `dtoverlay=spi0-0cs`
- creates a venv in `/opt/aft-inky-status` with Pimoroni's `inky` library
- installs and enables the `aft-inky-status` service

If it changed the SPI or I2C settings it asks you to reboot. Otherwise the display starts straight away. The display type is detected from the pHAT's EEPROM.

### How it updates

Each refresh flashes the panel and takes about 13 seconds on the red pHAT. The service checks every 30 seconds, or every 10 seconds while AFT is unhealthy. It redraws when anything shown changes, but at most once a minute. A change in AFT health or the IP address redraws at once.

At boot the screen first shows `Starting: server`, then `AFT OK` as soon as the stack is healthy. The panel keeps its last picture without power, so at shutdown it shows "Host shut down", and on a reboot "Restarting...". To show the shut-down notice by hand, stop the service, then run the script with `--offline`.

The service uses about 26 MB of memory and about 1% of the CPU.

### Settings

Settings are in `/etc/default/aft-inky-status`, and each one is explained in that file:
- how often it checks, and the minimum time between redraws
- turning the picture upside down
- the host and scheme in the URL
- container names

Apply changes with `sudo systemctl restart aft-inky-status`. Reinstalling keeps your settings.

To check the service, or render the screen to a PNG without the display:

```sh
systemctl status aft-inky-status
journalctl -u aft-inky-status -f          # one line per redraw
sudo /opt/aft-inky-status/venv/bin/python /opt/aft-inky-status/aft_inky_status.py --preview /tmp/inky.png
```

Stop the service before running a preview or test against the real display, because only one process can drive it.

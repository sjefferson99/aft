# AFT on a Raspberry Pi Zero 2 W

AFT can run on a Raspberry Pi Zero 2 W (512 MB RAM) for a small team or a portable demo. The Pi needs the OS and AFT tuning below to fit in memory. This folder holds the example files, and an optional status display for a Pimoroni Inky pHAT.

Tested with AFT v2026.11.2 on 64-bit Raspberry Pi OS Lite (Debian 13 trixie, kernel 6.18), headless, with Docker Engine 29. Tracked in [#723](https://github.com/sjefferson99/aft/issues/723).

| File | What it is |
|---|---|
| [`env.pi-zero-2w`](env.pi-zero-2w) | The `.env` values to change from `.env.example` |
| [`compose.override.pi-zero-2w.yaml`](compose.override.pi-zero-2w.yaml) | Gives the server time to start on a cold boot. Copy it as `compose.override.yaml` |
| [`inky-status/`](inky-status/) | Optional Inky pHAT status display, installed as a systemd service |
| [`wifi-hotspot/`](wifi-hotspot/) | Optional Wi-Fi hotspot when no saved network is in range, installed as a systemd service |
| [`../host-control/`](../host-control/) | Optional: restart or shut down the Pi from AFT's Instance Settings |

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
2. **Compose override:** copy [`compose.override.pi-zero-2w.yaml`](compose.override.pi-zero-2w.yaml) next to `compose.yml` as `compose.override.yaml`, which docker compose merges automatically. Without it, the server's healthcheck can time out on a cold boot, and nginx never starts.
3. **Origins:** add every address clients type into the browser to `CORS_ALLOWED_ORIGINS`, for example `https://aft-portable` and the Pi's IP address. Sign-in and live updates fail from any address that isn't listed.

The web container creates a self-signed certificate the first time it starts, so HTTPS works straight away. Browsers will warn about the certificate until you replace it with a real one (see [HTTPS and Session Cookie Security](../../www/docs/administration.md#https-and-session-cookie-security)).

**Gunicorn threads:** each open AFT tab holds one server thread for as long as it stays open, whether or not it's signed in. Once every thread is held, every request hangs until a tab closes. On the Pi, 8 threads served 7 open tabs, and holding them open cost about 2 MB more than 2 threads did. With 2 threads, two open tabs hung the server. Set `GUNICORN_THREADS` to at least 8, and raise it if more tabs will be open at once. Raise threads rather than workers: each extra worker costs about 80 MB.

The first `docker compose pull` and start are slow on a Pi Zero, so allow several minutes.

## 3. Optional: restart and shut down from AFT

A headless Pi has no clean way to power off, and pulling the power risks the SD card. [`../host-control/`](../host-control/) lets administrators restart or shut down the Pi from Instance Settings. See [Restarting or shutting down the host](../../www/docs/administration.md#restarting-or-shutting-down-the-host). With the Inky pHAT display installed, the screen shows "Restarting..." or "Host shut down" as the Pi goes down.

## 4. Optional: Inky pHAT status display

[`inky-status/`](inky-status/) shows the host's status on a [Pimoroni Inky pHAT](https://shop.pimoroni.com/products/inky-phat) e-ink display:

- the URL clients connect to (`https://<hostname>/`), with the IP address at the bottom for clients that can't resolve the name
- while the [Wi-Fi hotspot](#5-optional-wi-fi-hotspot) is up, how to join it in place of the URL and system figures: the network name, the password, `https://10.42.0.1/` and a QR code that phones can scan to join
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

Each refresh flashes the panel and takes about 13 seconds on the red pHAT. The service checks every 30 seconds, or every 10 seconds while AFT is unhealthy. It redraws when anything shown changes, but at most once a minute. A change in AFT health, the IP address or the hotspot redraws at once.

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

## 5. Optional: Wi-Fi hotspot

When the Pi is somewhere with no saved Wi-Fi network, such as a portable demo, clients have no way to reach it. [`wifi-hotspot/`](wifi-hotspot/) makes the Pi start its own Wi-Fi network in that case, so clients can join it and open AFT at `https://10.42.0.1/`. The hotspot only reaches AFT on the Pi: clients joined to it have no internet access.

It uses NetworkManager, which Raspberry Pi OS uses from bookworm on, so nothing else is installed except `iw`.

### How it works

- About 60 seconds after boot, if the Pi hasn't joined a saved network, it starts the hotspot. It does the same 60 seconds after losing a network.
- The hotspot is WPA2 only, with a password the installer makes up for each Pi. There's no way to run it as an open network.
- While the hotspot is up and no clients are connected, every 5 minutes it takes the hotspot down to look for a saved network, and joins one if it's in range. On the Pi a look took about 10 seconds, and longer if a saved network in range fails to connect. The Pi Zero 2 W has a single radio, so it can't look while the hotspot is up. While any client is connected it doesn't look, so a demo isn't interrupted.
- With a saved network in range, nothing changes.

### Before you install

1. **Wi-Fi country:** the hotspot needs one set. Raspberry Pi Imager sets it with the Wi-Fi details. Check with `iw reg get`, and set it with `sudo raspi-config nonint do_wifi_country GB`, using your country code.
2. **Origins:** add `https://10.42.0.1` to `CORS_ALLOWED_ORIGINS` in AFT's `.env`, then run `docker compose up -d`. Clients on the hotspot usually can't resolve the Pi's name, so they use this address, and sign-in and live updates fail from an address that isn't listed. For example:

   ```sh
   CORS_ALLOWED_ORIGINS=https://aft-portable,https://192.168.1.50,https://10.42.0.1
   ```

### Install

Copy the `wifi-hotspot` folder to the Pi, then run:

```sh
cd wifi-hotspot
sudo ./install.sh
```

The installer installs the `aft-wifi-fallback` service and the `aft-hotspot` command, creates the settings with a new password, and shows the network name and password. Reinstalling keeps your settings. To remove it, run `sudo ./uninstall.sh`.

### Joining the hotspot

Join the network shown by `sudo aft-hotspot status`, or on the Inky pHAT display, then open `https://10.42.0.1/`. With the display installed, phones can join by scanning the QR code on it. If you installed the display before the hotspot existed, run its `install.sh` again to add the QR code package. Browsers warn about the self-signed certificate, as they do on any address.

To sign in to the Pi with SSH while it's running the hotspot, join the hotspot and use `ssh <user>@10.42.0.1`.

### Using the hotspot with a saved network in range

To run the hotspot even where the Pi could join a saved network, for example so that clients at a demo join the Pi directly, switch the mode:

```sh
sudo aft-hotspot always   # keep the hotspot up and never join a saved network
sudo aft-hotspot auto     # the default: start the hotspot only when no saved network is in range
sudo aft-hotspot off      # never start the hotspot
```

Switching to `always` takes the Pi off its saved network straight away, so an SSH session over that network ends. Join the hotspot to sign in again. Switching back to `auto` looks for a saved network straight away, unless clients are still joined to the hotspot. The mode is kept across restarts.

### Settings

Settings are in `/etc/default/aft-wifi-fallback`, which only root can read because it holds the password. Each one is explained in the file:
- the mode, network name and password
- the 2.4 GHz channel, 6 unless you change it
- how long to wait before starting the hotspot, how often to look for a saved network, and how long to wait for one to connect

Apply changes with `sudo systemctl restart aft-wifi-fallback`. A new password or network name disconnects clients from the hotspot. Check the service with `systemctl status aft-wifi-fallback` and `journalctl -u aft-wifi-fallback`, which logs a line each time the hotspot starts or a saved network is joined.

### Memory

Measured on the Pi Zero 2 W: the service uses about 9 MB, part of it in swap, and about 1% of the CPU. While the hotspot is up, NetworkManager's dnsmasq, which gives clients their addresses, uses another 2 to 4 MB. Other memory use didn't change measurably.

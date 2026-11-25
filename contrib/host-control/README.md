# AFT host restart and shut down

Lets AFT administrators restart or shut down the machine AFT runs on from **Instance Settings**. Only for hosts dedicated to AFT, such as a Raspberry Pi appliance: it powers off everything on the host. Tracked in [#726](https://github.com/sjefferson99/aft/issues/726). Setup and use are described in [Restarting or shutting down the host](../../www/docs/administration.md#restarting-or-shutting-down-the-host).

The AFT server container stays unprivileged. It writes `reboot` or `poweroff` to the file `request` in a folder mounted from the host, and these units act on it:

| File | What it is |
|---|---|
| [`aft-host-control.path`](aft-host-control.path) | Starts the service when the `request` file appears |
| [`aft-host-control.service`](aft-host-control.service) | Runs the script once per request |
| [`aft-host-control-clear.service`](aft-host-control-clear.service) | Deletes a request left from before a boot, before the path unit starts watching |
| [`aft-host-control`](aft-host-control) | Deletes the request, then runs `systemctl reboot` or `systemctl poweroff`. It ignores anything else, and anything that isn't a regular file |
| [`install.sh`](install.sh) / [`uninstall.sh`](uninstall.sh) | Install or remove all of the above |

## Install

```sh
sudo ./install.sh /opt/docker/aft/host-control
```

Give the folder next to your `compose.yml` that you mount into the server container as `/app/host-control`. The installer creates it owned by uid 1000, the server container's user (set `AFT_UID` to change that), installs the script to `/usr/local/libexec`, writes the folder to `/etc/default/aft-host-control`, and enables the units. Then mount the folder and set `HOST_POWER_CONTROL=true` in `.env`.

## Check it

```sh
systemctl status aft-host-control.path
journalctl -u aft-host-control -u aft-host-control-clear
```

To test the units without restarting, write something that isn't an action. The service deletes it and logs `Ignored an unrecognised request`:

```sh
echo test | sudo -u '#1000' tee /opt/docker/aft/host-control/request
```

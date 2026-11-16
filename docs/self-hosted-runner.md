# Setting up a Self-Hosted GitHub Actions Runner

A self-hosted runner runs GitHub Actions jobs on your own machine (or home server)
instead of GitHub's cloud VMs. This means zero Actions minutes consumed — it is
completely free regardless of how many builds you run.

## Prerequisites

- Docker must be installed on the machine that will act as the runner
- The machine must have internet access to reach GitHub and GHCR
- Windows, Linux, or macOS are all supported
- The runner's Docker daemon must allow privileged containers (used by
  `docker/setup-qemu-action` to register binfmt handlers for cross-building
  `linux/arm64` images, e.g. for Raspberry Pi)

---

## 1. Register the runner with your repository

1. Go to your repo on GitHub → **Settings** → **Actions** → **Runners**
2. Click **New self-hosted runner**
3. Choose your OS and follow the download/configure steps shown on screen.
   The key command will look like:

   ```sh
   # Linux example (GitHub generates the exact token for you)
   ./config.sh --url https://github.com/sjefferson99/aft --token <YOUR_TOKEN>
   ```

4. When prompted for labels, the default (`self-hosted`) is all the workflow
   needs. You can add extras (e.g. `linux`, `docker`) but it is not required.

---

## 2. Run the runner as a service (so it survives reboots)

**Linux (systemd)**

```sh
sudo ./svc.sh install
sudo ./svc.sh start
```

**Windows (as a service)**

Run the following in an elevated PowerShell prompt from the runner directory:

```powershell
.\svc.cmd install
.\svc.cmd start
```

Or use the interactive method during development — just run `./run.sh` (Linux)
or `.\run.cmd` (Windows) in a terminal and keep it open.

---

## 3. Verify it is connected

Back on GitHub → **Settings** → **Actions** → **Runners** — the runner should
show a green **Idle** status.

---

## 4. Triggering a build

The workflow (`.github/workflows/build-and-push.yml`) runs on three triggers:

| Trigger | Tags pushed |
|---|---|
| Push to `main` (merging a PR) | `edge`, `sha-…` |
| Publishing a release `vX.Y.Z` | `X.Y.Z`, `X.Y`, `latest`, `sha-…` |
| Manual run (Actions tab) on a branch | `dev-<branch>`, `sha-…` |
| Manual run on `main` | `edge`, `sha-…` |

`latest` only moves when a release is published, so self-hosters on the default
compose file stay on the newest release. To cut a release:

1. Merge your work to `main` as normal (this updates `edge`)
2. When ready to cut a release, go to GitHub → **Releases** → **Draft a new release**
3. Create a tag in the form `vX.Y.Z` (e.g. `v2026.11.1`) and publish
4. The runner picks up the job, builds both images for `linux/amd64` and
   `linux/arm64`, and pushes a single multi-arch manifest per tag to GHCR.
   `docker pull`/`docker compose pull` automatically grabs the right
   architecture, so the same images run on a Raspberry Pi without changes.
   The `arm64` leg is built via QEMU emulation, so builds take noticeably
   longer than amd64-only builds did.

Images will be available at:
- `ghcr.io/sjefferson99/aft:latest`, `ghcr.io/sjefferson99/aft:2026.11.1` and `ghcr.io/sjefferson99/aft:edge`
- `ghcr.io/sjefferson99/aft-web:latest`, `ghcr.io/sjefferson99/aft-web:2026.11.1` and `ghcr.io/sjefferson99/aft-web:edge`

---

## 5. Making the GHCR packages public (optional but recommended for `docker pull`)

By default, packages pushed by a new workflow are **private**. To allow
unauthenticated `docker pull`:

1. Go to `https://github.com/sjefferson99?tab=packages`
2. Click the package (e.g. `aft`) → **Package settings**
3. Scroll to **Danger Zone** → **Change visibility** → **Public**

Repeat for `aft-web`. Once public, anyone can run:

```sh
docker pull ghcr.io/sjefferson99/aft:latest
docker pull ghcr.io/sjefferson99/aft-web:latest
```

---

## 6. Deploying with the production compose file

On any server (no repo clone needed — just a `.env` file):

```sh
# Download the default compose file
curl -O https://raw.githubusercontent.com/sjefferson99/aft/main/compose.example.yml

# Create your .env with DB credentials, SECRET_KEY, HEALTHCHECK_TOKEN, etc.
nano .env

# Pull latest images and start the stack
docker compose -f compose.example.yml pull
docker compose -f compose.example.yml up -d
```

To update to a newer release in future:

```sh
docker compose -f compose.example.yml pull
docker compose -f compose.example.yml up -d
```

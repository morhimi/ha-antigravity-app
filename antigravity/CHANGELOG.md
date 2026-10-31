# Changelog

## 1.3.1

- Updated Remote Control portal links in documentation and UI translations to `https://antigravity.google.com/`.
- Added `.github/dependabot.yml` for automated weekly GitHub Actions and Docker dependency checks.

## 1.3.0

- Added `ssh_private_key` App configuration option (accepting a file path such as `/ssl/id_ed25519`, a Base64-encoded key, or a raw OpenSSH private key) with automatic public key derivation (`ssh-keygen -y`) and validation.
- Automatically generates a persistent `/data/.ssh/id_ed25519` keypair on first boot if none exists, configures `/data/.ssh/config` (`StrictHostKeyChecking accept-new`), and prints the active SSH public key in the App startup log and Web UI welcome banner.

## 1.2.0

- Added `permission_mode` App configuration option (`turbo`, `auto`, `default`, `request_review`, defaulting to `turbo`) that configures both `~/.gemini/config/config.json` (used by Remote Control / Antigravity 2.0) and `~/.gemini/antigravity-cli/settings.json` (used by interactive CLI sessions), plus pre-trusts Home Assistant workspace directories.

## 1.1.4

- Fixed `agy-remote` healthcheck regex (`Daemon status: active` vs `Daemon state = active`) that caused the supervisor loop to restart the Remote Control daemon every 18 seconds and disconnect active remote sessions.
- Set `ttyd --debug 1` so the 30-second local Docker `HEALTHCHECK` (`HTTP / - 127.0.0.1`) no longer spams `libwebsockets` connection logs.
- Prevented `s6-svwait: fatal: timed out` on container shutdown by exiting immediately in `agy-remote/finish` when stopped cleanly.

## 1.1.3

- Added post-login confirmation banner in the Web UI displaying the clickable `https://antigravity.google.com/` Remote Control portal URL and instance name, and eliminated the duplicate first-time sign-in prompt loop.
- Added periodic 24-hour background `agy update` check in `agy-remote` (when `auto_update_cli: true`) so long-running containers automatically update `agy` and reload the daemon when new upstream versions are released.

## 1.1.2

- Replaced placeholder app icon and logo with the official Google Antigravity icon.
- Automated GitHub Release creation in CI after multi-arch image publication.

## 1.1.1

- Fixed broken/truncated Google OAuth URL in the Ingress web terminal (`ttyd`) by running first-time authentication via `agy -p` directly in `ttyd` (without `tmux` / TUI box margin line-splitting or mouse capture), keeping the entire OAuth URL clickable as a single unbroken link.

## 1.1.0

- Upgraded base image to **Debian 13 (`trixie`)** via `ghcr.io/home-assistant/base-debian:trixie`.
- Updated repository and app configuration (`all_app_configs:rw`, `local_apps:rw`, `io.hass.type=app`, `ghcr.io/morhimi/app-antigravity`) to align with Home Assistant's **Apps** terminology and standards.

## 1.0.0

- Initial release of the **Antigravity CLI (`agy`)** Home Assistant App.
- Multi-arch Debian container (`amd64` and `aarch64`) with `s6-overlay` v3 supervision.
- Supervised `agy remote-control` daemon for 24/7 remote access from [antigravity.google](https://antigravity.google) and mobile devices.
- Integrated Home Assistant Ingress Web UI (`ttyd` + `tmux`) for one-step interactive Google Account sign-in and sidebar terminal access.
- Full persistence in `/data` across app updates and reboots (`~/.gemini`, `~/.ssh`, `~/.config`, `/data/bin/agy`).
- Pre-installed `ha` CLI, `git`, `python3`, `ripgrep`, `fd-find`, `jq`, and automatic Home Assistant MCP (`/api/mcp`) configuration.

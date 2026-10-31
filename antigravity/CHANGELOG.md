# Changelog

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

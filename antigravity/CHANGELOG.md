# Changelog

## 1.0.0

- Initial release of the **Antigravity CLI (`agy`)** Home Assistant Add-on.
- Multi-arch Debian 12 (`bookworm`) container (`amd64` and `aarch64`) built on `ghcr.io/home-assistant/base-debian:bookworm`.
- Supervised `agy remote-control` daemon via `s6-overlay` v3 for 24/7 remote access from [antigravity.google](https://antigravity.google) and mobile devices.
- Integrated Home Assistant Ingress Web UI (`ttyd` + `tmux`) for one-step interactive Google Account sign-in and sidebar terminal access.
- Full persistence in `/data` across add-on updates and reboots (`~/.gemini`, `~/.ssh`, `~/.config`, `/data/bin/agy`).
- Pre-installed `ha` CLI, `git`, `python3`, `ripgrep`, `fd-find`, `jq`, and automatic Home Assistant MCP (`/api/mcp`) configuration.

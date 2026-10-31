# Antigravity Home Assistant App Repository

[![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmorhimi%2Fha-antigravity-app)
[![Build & Publish](https://github.com/morhimi/ha-antigravity-app/actions/workflows/builder.yaml/badge.svg)](https://github.com/morhimi/ha-antigravity-app/actions/workflows/builder.yaml)
[![Lint](https://github.com/morhimi/ha-antigravity-app/actions/workflows/lint.yaml/badge.svg)](https://github.com/morhimi/ha-antigravity-app/actions/workflows/lint.yaml)

This repository provides a Home Assistant App that runs the **Google Antigravity CLI (`agy`)** as an always-on, supervised background service on your Home Assistant server.

## Apps in this Repository

### [Antigravity CLI (`antigravity`)](./antigravity)

Run **Google Antigravity (`agy`)** 24/7 on your Home Assistant server without keeping your laptop open:

- **Native Remote Control Daemon (`agy remote-control`)**: Supervised by `s6-overlay` so you can start, monitor, and control agent sessions from any browser at [antigravity.google](https://antigravity.google) or the mobile app (iOS / Android).
- **Home Assistant Ingress Web Terminal (`ttyd` + `tmux`)**: One-click interactive terminal inside the Home Assistant sidebar (`Antigravity`) for initial Google Account sign-in and direct interactive CLI sessions.
- **Full Persistence Across Updates & Reboots**: Credentials, conversation transcripts, skills, rules, plugins, SSH keys, and CLI self-updates are stored inside the app's persistent `/data` volume.
- **Built-in Home Assistant Tooling**: Pre-installed on Debian 13 (`trixie`) with the official `ha` CLI, `git`, `python3`, `ripgrep`, `jq`, `ssh`, and automatic configuration for Home Assistant's native Model Context Protocol (`/api/mcp`) endpoint.
- **Multi-Arch Pre-Built Images**: Automatically built and signed via GitHub Actions (`amd64` and `aarch64`) on `ghcr.io/morhimi/app-antigravity`.

---

## Quick Installation

1. Click the **Add Repository to My Home Assistant** button above, or in Home Assistant navigate to:
   **Settings → Apps → App Store → ⋮ (top right) → Repositories** and add:
   ```text
   https://github.com/morhimi/ha-antigravity-app
   ```
2. Find **Antigravity CLI** in the App Store and click **Install**.
3. Toggle **Start on boot**, **Watchdog**, and **Show in sidebar**, then click **Start**.
4. Click **Open Web UI** (or **Antigravity** in the sidebar) to complete the one-time Google Account sign-in. Once signed in, the background `agy remote-control` daemon starts automatically.

---

## License

MIT License — see [LICENSE](./LICENSE).

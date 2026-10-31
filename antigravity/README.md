# Home Assistant App: Antigravity CLI

Run the **Google Antigravity CLI (`agy`)** 24/7 on your Home Assistant server with native **Remote Control** and an integrated **Home Assistant Ingress Web Terminal**.

## Features

- **24/7 Remote Control Daemon**: Runs `agy remote-control` supervised by `s6-overlay` so you can start, inspect, and control agent sessions from any web browser ([antigravity.google.com](https://antigravity.google.com/)) or the mobile app—without keeping your laptop awake.
- **Sidebar Web Terminal (Ingress)**: Includes `ttyd` + `tmux` integrated directly into the Home Assistant UI for easy first-time Google Account sign-in and interactive terminal sessions.
- **Persistent State & Self-Updates**: All credentials, conversations, skills, rules, plugins, SSH keys, and CLI binaries are persisted in `/data` across app updates and host reboots.
- **Home Assistant Native Tooling**: Built on Debian 13 (`trixie`) with the official `ha` CLI (`ha core check`, `ha core restart`, `ha core logs`), `git`, `python3`, `ripgrep`, `jq`, and automatic configuration for Home Assistant's `/api/mcp` Model Context Protocol server.

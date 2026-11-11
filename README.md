# Google Antigravity CLI & Gemini AI App (Add-on) for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/morhimi/ha-antigravity-app?label=version&logo=github)](https://github.com/morhimi/ha-antigravity-app/releases)
[![Build & Publish](https://github.com/morhimi/ha-antigravity-app/actions/workflows/builder.yaml/badge.svg)](https://github.com/morhimi/ha-antigravity-app/actions/workflows/builder.yaml)
[![Lint, Security & Smoke Test](https://github.com/morhimi/ha-antigravity-app/actions/workflows/lint.yaml/badge.svg)](https://github.com/morhimi/ha-antigravity-app/actions/workflows/lint.yaml)
[![Auto-Update Upstream Dependencies](https://github.com/morhimi/ha-antigravity-app/actions/workflows/auto-update.yaml/badge.svg)](https://github.com/morhimi/ha-antigravity-app/actions/workflows/auto-update.yaml)
[![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-green.svg)](#)
[![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-green.svg)](#)
[![License: MIT](https://img.shields.io/github/license/morhimi/ha-antigravity-app)](./LICENSE)

[![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmorhimi%2Fha-antigravity-app)

Run **Google Antigravity CLI (`agy`)** and **Google Gemini (Pro / Flash)** 24/7 natively inside **Home Assistant OS / Supervised** as an always-on App (Add-on) — complete with **Remote Control**, **Model Context Protocol (MCP)** integration, and a **local REST API bridge (`:8120`)** for multimodal camera, doorbell video, and smart-home automations.

---

## Key Features & Capabilities

### [Antigravity CLI (`antigravity`)](./antigravity)

- **Local Gemini Multimodal REST API Bridge (`:8120/api/generate`)**:
  Trigger **Google Gemini** directly from Home Assistant automations (`rest_command` with `response_variable`) using your existing Google Antigravity / Google AI subscription — **no free-tier AI Studio `429` rate limits**. Supports native multimodal analysis of `/media/...` security camera snapshots, doorbell `.mp4` video clips, and audio files.
- **24/7 Remote Control Daemon (`agy remote-control`)**:
  Supervised by `s6-overlay` so you can start, monitor, and control autonomous coding and smart-home management sessions from any browser at [antigravity.google.com](https://antigravity.google.com/) or the mobile app (iOS / Android) without keeping your laptop awake.
- **Native Home Assistant MCP Server Integration (`/api/mcp`)**:
  Automatically provisions `~/.gemini/config/mcp_config.json` to connect Antigravity to your Home Assistant Model Context Protocol server, giving Gemini live context over entities, automations, scripts, and device states.
- **Home Assistant Ingress Web Terminal (`ttyd`)**:
  One-click interactive terminal inside the Home Assistant sidebar (`Antigravity`) for initial Google Account OAuth sign-in and interactive `agy` CLI sessions.
- **Full Persistence Across Updates & Reboots (`/data`)**:
  Google OAuth tokens, conversation transcripts, skills, rules, plugins, SSH keys (`/data/.ssh/id_ed25519`), and in-place CLI self-updates persist across container restarts and App upgrades.
- **Pre-Installed Smart-Home & Developer Tooling**:
  Built on Debian 13 (`trixie`) for `amd64` and `aarch64` (`ghcr.io/morhimi/app-antigravity`) with the official `ha` CLI, `git`, `python3`, `ripgrep`, `jq`, `curl`, and `openssh-client`.

---

## Popular Home Assistant + Gemini / Antigravity Use Cases

1. **Multimodal Camera & Doorbell Video Analysis (No `429` Quota Errors)**:
   Pass recorded `.mp4` clips or `.jpg` snapshots from `/media/...` to `POST http://68eea963-antigravity:8120/api/generate` and receive structured descriptions for mobile push notifications or TTS announcements.
2. **Autonomous Home Assistant Configuration & Debugging via Remote Control**:
   Open [antigravity.google.com](https://antigravity.google.com/) from your phone or browser to ask your Home Assistant `agy` instance to inspect `/homeassistant/configuration.yaml`, write automations, check logs via `ha core logs`, or debug integrations.
3. **Fleet & Network Management via Persistent SSH**:
   Use the auto-generated `/data/.ssh/id_ed25519.pub` key to let Antigravity manage OpenWrt routers, ESPHome nodes, or local Linux servers directly from your Home Assistant host.

---

## Example: Calling Gemini from a Home Assistant Automation (`rest_command`)

Add to your `/homeassistant/configuration.yaml`:

```yaml
rest_command:
  antigravity_generate:
    url: "http://68eea963-antigravity:8120/api/generate"
    method: POST
    content_type: "application/json"
    timeout: 120
    payload: >-
      {
        "prompt": {{ prompt | tojson }},
        "files": {{ files | default([]) | tojson }},
        "model": "{{ model | default('gemini-3.8-flash-low') }}",
        "timeout": {{ timeout | default(120) | int }}
      }
```

Then invoke it in any automation or script with `response_variable`:

```yaml
action: rest_command.antigravity_generate
data:
  prompt: "Describe who is at the front door in one sentence."
  files:
    - "/media/doorbell/latest_clip.mp4"
  model: "gemini-3.8-flash-low"
response_variable: agy_res
```

The clean model output is returned in `{{ agy_res['content']['response'] }}`. See the full [App Documentation (`antigravity/DOCS.md`)](./antigravity/DOCS.md) for all configuration options.

---

## Quick Installation

1. Click the **Add Repository to My Home Assistant** button at the top of this page, or in Home Assistant navigate to:
   **Settings → Apps → App Store → ⋮ (top right) → Repositories** and add:
   ```text
   https://github.com/morhimi/ha-antigravity-app
   ```
2. Find **Antigravity CLI** in the App Store and click **Install**.
3. Toggle **Start on boot**, **Watchdog**, and **Show in sidebar**, then click **Start**.
4. Click **Open Web UI** (or **Antigravity** in the sidebar) to complete the one-time Google Account sign-in. Once signed in, both the `agy remote-control` daemon and the `agy-api` REST server on port `8120` run automatically.

---

## License

MIT License — see [LICENSE](./LICENSE).

# Home Assistant App: Antigravity CLI Documentation

This app runs the **Google Antigravity CLI (`agy`)** inside a persistent Debian 13 (`trixie` / `glibc`) environment supervised by Home Assistant.

---

## First-Time Setup & Authentication

1. Install and **Start** the **Antigravity CLI** app.
2. Click **Open Web UI** (or select **Antigravity** from your Home Assistant sidebar).
3. On first launch, the Ingress web terminal prompts for one-time Google Account authentication:
   - Click the displayed Google authentication URL.
   - Sign in with your Google Account and paste the authorization code back into the terminal.
4. Once authenticated:
   - Your credentials are saved permanently in `/data/.gemini`.
   - The background `agy-remote` service automatically launches the `agy remote-control` daemon under your configured **Instance Name** (default: `home-assistant`).
   - Open [https://antigravity.google.com/](https://antigravity.google.com/) from any browser or mobile device to connect to your `home-assistant` instance remotely.

---

## Configuration Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `instance_name` | `"home-assistant"` | Machine name displayed in Antigravity Remote Control. |
| `permission_mode` | `"turbo"` | Default working/permission mode (`turbo`, `auto`, `default`, `request_review`) applied to both Remote Control (`config.json`) and interactive CLI (`settings.json`). |
| `remote_control` | `true` | Keep the `agy remote-control` daemon running in the background. |
| `auto_update_cli` | `true` | Automatically update the `/data/bin/agy` binary to the latest upstream release on app startup. |
| `workspace_dir` | `"/homeassistant"` | Default working directory (`/homeassistant` is also symlinked at `/config`). |
| `api_enabled` | `true` | Run the local HTTP REST API daemon (`agy-api`) on `api_port` for Home Assistant automations. |
| `api_port` | `8120` | Internal TCP port for the local REST API daemon. |
| `default_model` | `"gemini-4-hydrogen-low"` | Default model used by `/api/generate` when `model` is omitted in the request payload. |
| `default_timeout` | `120` | Default timeout (10–600 seconds) for `/api/generate` when `timeout` is omitted in the request payload. |
| `ha_mcp_enabled` | `true` | Automatically configure `~/.gemini/config/mcp_config.json` with the `home-assistant` MCP server when `ha_mcp_token` is provided. |
| `ha_mcp_url` | `"http://homeassistant:8123/api/mcp"` | Home Assistant native MCP server endpoint. |
| `ha_mcp_token` | *(optional)* | Long-Lived Access Token from your Home Assistant user profile for `/api/mcp`. |
| `ssh_private_key` | *(optional)* | SSH private key for connecting to external hosts (e.g., OpenWrt APs). Accepts a file path (`/ssl/id_ed25519`), a Base64-encoded key (`base64 < ~/.ssh/id_ed25519 \| tr -d '\n'`), or a raw OpenSSH private key. If left blank, a persistent Ed25519 keypair is generated in `/data/.ssh/id_ed25519` and its public key is printed in the App startup log and Web UI banner. |
| `gemini_api_key` | *(optional)* | Optional `GEMINI_API_KEY` if authenticating with an API key instead of OAuth. |
| `log_level` | `"info"` | App script log verbosity (`trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`). |

---

## Local REST API for Automations (`agy-api`)

When `api_enabled: true`, the app runs a lightweight async HTTP REST daemon on port `8120` (`POST /api/generate` and `GET /health`) so Home Assistant automations can invoke `agy -p` with prompts and media files (`/media/...`).

Example `configuration.yaml` setup:

```yaml
rest_command:
  antigravity_vision:
    url: "http://68eea963-antigravity:8120/api/generate"
    method: POST
    content_type: "application/json"
    timeout: 120
    payload: >-
      {
        "prompt": {{ prompt | tojson }},
        "files": {{ files | default([]) | tojson }},
        "model": "{{ model | default('gemini-4-hydrogen-low') }}",
        "timeout": {{ timeout | default(120) | int }}
      }
```

The JSON response (`{"status": "success", "response": "...", "model": "...", "duration_seconds": ..., "conversation_id": "..."}`) is returned in `response_variable['content']['response']`.

### Advanced REST API Features

- **Structured JSON Outputs (`json_schema`)**: Pass `"json_schema": {"type": "object", "properties": {"person_detected": {"type": "boolean"}}, "required": ["person_detected"]}` in the payload to receive a parsed `"structured"` JSON object in `agy_res['content']['structured']`.
- **Conversation Continuity (`conversation_id`)**: Pass `"conversation_id"` from a previous call to continue an ongoing session (`agy --conversation <id>`).
- **Non-Blocking Async Events (`async: true`)**: Pass `"async": true` and `"event_type": "agy_camera_done"` (plus optional `"request_id"` / `"metadata"`) to receive an immediate `202 Accepted` response and trigger an automation on the resulting Home Assistant event (`trigger: event`, `event_type: agy_camera_done`).
- **Session Auth Healthcheck (`GET /health`)**: Poll `http://68eea963-antigravity:8120/health` with a RESTful `binary_sensor` checking `value_json.authenticated` to be notified if your Google OAuth session expires.

---

## Persistence & Mapped Directories

All stateful data lives on `/data` and survives app restarts, container upgrades, and Home Assistant OS updates:

- `/data/bin/agy` (symlinked at `/usr/local/bin/agy`): Allows `agy` to self-update in-place without losing updates on container restart.
- `/data/.gemini` (symlinked at `/root/.gemini`): Stores OAuth tokens, `settings.json`, `mcp_config.json`, skills, rules, plugins, and conversation transcripts.
- `/data/.ssh` (symlinked at `/root/.ssh`): Stores SSH keys and `known_hosts` for managing external hosts/routers.
- `/data/.local` (symlinked at `/root/.local`): Preserves user-installed tools and Python packages (`~/.local/bin`).
- `/data/workspace` (symlinked at `/root/workspace`): Persistent general-purpose workspace directory inside `/root`.
- `/homeassistant` (also symlinked at `/config`): Your Home Assistant configuration directory (`rw`).
- `/share`, `/media`, `/backup`, `/local_apps`, `/app_configs`: Mounted for full system administration.

> **Important:** Container rebuilds during App updates reset everything outside `/data` and Home Assistant mapped volumes. Always keep project workspaces under `/homeassistant` or `/data/workspace` (`~/workspace`), not in ad-hoc `/root/<folder>` paths.

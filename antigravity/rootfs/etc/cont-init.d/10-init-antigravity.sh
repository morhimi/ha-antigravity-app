#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# ==============================================================================
# Home Assistant App: Antigravity CLI
# Initializes persistent storage, CLI binary, and MCP configuration
# ==============================================================================

set -euo pipefail

if bashio::config.has_value 'log_level'; then
    bashio::log.level "$(bashio::config 'log_level')"
fi

bashio::log.info "Initializing Antigravity CLI persistent environment..."

# 1. Create persistent directories in /data
mkdir -p \
    /data/bin \
    /data/.gemini/antigravity-cli \
    /data/.gemini/config \
    /data/.ssh \
    /data/.config \
    /data/workspace

chmod 700 /data/.ssh

# 2. Link root dotfiles to persistent /data storage
for item in .gemini .ssh .config; do
    if [ -d "/root/${item}" ] && [ ! -L "/root/${item}" ]; then
        cp -rn "/root/${item}/." "/data/${item}/" 2>/dev/null || true
        rm -rf "/root/${item}"
    fi
    ln -sfn "/data/${item}" "/root/${item}"
done

if [ ! -f /data/.gitconfig ]; then
    touch /data/.gitconfig
fi
ln -sfn /data/.gitconfig /root/.gitconfig

# 3. Ensure /config symlink points to /homeassistant for convenience
if [ -d /homeassistant ] && [ ! -e /config ]; then
    ln -sfn /homeassistant /config
fi

# 4. Provision /data/bin/agy and optionally update from upstream
if [ ! -x /data/bin/agy ]; then
    bashio::log.info "Copying baked-in Antigravity CLI binary to /data/bin/agy..."
    cp -f /opt/antigravity/bin/agy /data/bin/agy
    chmod +x /data/bin/agy
fi

if bashio::config.true 'auto_update_cli'; then
    bashio::log.info "Checking for latest upstream Antigravity CLI release..."
    stage_dir="/tmp/agy-update-stage"
    rm -rf "${stage_dir}"
    mkdir -p "${stage_dir}"
    if curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- --dir "${stage_dir}" >/dev/null 2>&1; then
        if [ -x "${stage_dir}/agy" ]; then
            mv -f "${stage_dir}/agy" /data/bin/agy
            chmod +x /data/bin/agy
            bashio::log.info "Antigravity CLI updated to version $(/data/bin/agy --version 2>/dev/null || echo 'latest')."
        fi
    else
        bashio::log.warning "Could not reach upstream update server; keeping existing /data/bin/agy."
    fi
    rm -rf "${stage_dir}"
fi

ln -sfn /data/bin/agy /usr/local/bin/agy

# 5. Configure Remote Control instance name and default working/permission mode
instance_name="$(bashio::config 'instance_name')"
if [ -n "${instance_name}" ]; then
    printf '%s' "${instance_name}" > /data/.gemini/antigravity-cli/remote-control-name
    bashio::log.info "Configured Remote Control instance name: ${instance_name}"
fi

permission_mode="$(bashio::config 'permission_mode')"
workspace_dir="$(bashio::config 'workspace_dir')"
/usr/local/bin/agy-apply-mode "${permission_mode}" "${workspace_dir}"
bashio::log.info "Configured Antigravity working/permission mode: ${permission_mode}"

# 6. Configure optional GEMINI_API_KEY in s6 container environment
if bashio::config.has_value 'gemini_api_key'; then
    mkdir -p /run/s6/container_environment
    printf '%s' "$(bashio::config 'gemini_api_key')" > /run/s6/container_environment/GEMINI_API_KEY
    bashio::log.info "Configured GEMINI_API_KEY in container environment."
fi

# 7. Auto-configure Home Assistant native MCP server in ~/.gemini/config/mcp_config.json
mcp_file="/data/.gemini/config/mcp_config.json"
if [ ! -f "${mcp_file}" ]; then
    echo '{"mcpServers":{}}' > "${mcp_file}"
fi

if bashio::config.true 'ha_mcp_enabled' && bashio::config.has_value 'ha_mcp_token'; then
    ha_mcp_url="$(bashio::config 'ha_mcp_url')"
    ha_mcp_token="$(bashio::config 'ha_mcp_token')"
    tmp_mcp="$(mktemp)"
    if jq \
        --arg url "${ha_mcp_url}" \
        --arg auth "Bearer ${ha_mcp_token}" \
        '.mcpServers["home-assistant"] = {
            "url": $url,
            "headers": {
                "Authorization": $auth,
                "Accept": "application/json"
            }
        }' "${mcp_file}" > "${tmp_mcp}"; then
        mv "${tmp_mcp}" "${mcp_file}"
        chmod 600 "${mcp_file}"
        bashio::log.info "Configured Home Assistant MCP server (${ha_mcp_url}) in ${mcp_file}."
    else
        rm -f "${tmp_mcp}"
        bashio::log.warning "Failed to update ${mcp_file}; preserving existing file."
    fi
fi

# 8. Create persistent tmux configuration if not present
if [ ! -f /data/.tmux.conf ]; then
    cat << 'EOF' > /data/.tmux.conf
set -g default-terminal "xterm-256color"
set -ga terminal-overrides ",*256col*:Tc"
set -g mouse on
set -s set-clipboard on
set -g history-limit 50000
set -g status-bg colour235
set -g status-fg white
set -g status-left "#[fg=cyan,bold] Antigravity CLI #[default]| "
set -g status-left-length 30
set -g status-right "#[fg=green]#(/usr/local/bin/agy --version 2>/dev/null)#[default] | %H:%M "
EOF
fi
ln -sfn /data/.tmux.conf /root/.tmux.conf

# 9. Configure interactive shell environment
cat << 'EOF' > /etc/profile.d/antigravity.sh
export HOME="/root"
export SHELL="/bin/bash"
export TERM="xterm-256color"
export SSH_CONNECTION="127.0.0.1 0 127.0.0.1 22"
export PATH="/data/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EOF

if ! grep -q "/etc/profile.d/antigravity.sh" /root/.bashrc 2>/dev/null; then
    cat << 'EOF' >> /root/.bashrc

# Antigravity CLI environment
if [ -f /etc/profile.d/antigravity.sh ]; then
    . /etc/profile.d/antigravity.sh
fi
alias agy-status='agy remote-control status'
EOF
fi

bashio::log.info "Antigravity CLI initialization complete."

# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM=ghcr.io/home-assistant/base-debian:bookworm
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG TARGETARCH
ARG TTYD_VERSION=1.7.7
ARG HA_CLI_VERSION=5.6.0

# Install developer and system administration packages
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        dnsutils \
        fd-find \
        git \
        iputils-ping \
        less \
        nano \
        netcat-openbsd \
        openssh-client \
        procps \
        python3 \
        python3-pip \
        python3-venv \
        ripgrep \
        sqlite3 \
        tmux \
        vim-tiny \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# Install ttyd (Ingress web terminal) and Home Assistant CLI (ha)
RUN \
    if [ -z "${TARGETARCH}" ]; then \
        echo "TARGETARCH is not set, please use Docker BuildKit for the build." && exit 1; \
    fi \
    && case "${TARGETARCH}" in \
        amd64) \
            ttyd_arch="x86_64"; \
            ha_arch="amd64"; \
            ;; \
        arm64) \
            ttyd_arch="aarch64"; \
            ha_arch="aarch64"; \
            ;; \
        *) \
            echo "Unsupported TARGETARCH: ${TARGETARCH}" && exit 1; \
            ;; \
    esac \
    && curl -fsSL -o /usr/bin/ttyd \
        "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${ttyd_arch}" \
    && chmod +x /usr/bin/ttyd \
    && curl -fsSL -o /usr/bin/ha \
        "https://github.com/home-assistant/cli/releases/download/${HA_CLI_VERSION}/ha_${ha_arch}" \
    && chmod +x /usr/bin/ha

# Pre-install Google Antigravity CLI (agy) into /opt/antigravity/bin
RUN \
    mkdir -p /opt/antigravity/bin \
    && curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- --dir /opt/antigravity/bin \
    && rm -rf /root/.cache

# Copy root filesystem
COPY rootfs /

# Ensure all lifecycle and helper scripts are executable
RUN \
    chmod +x \
        /etc/cont-init.d/* \
        /etc/services.d/*/run \
        /etc/services.d/*/finish \
        /usr/local/bin/agy-*

ENV \
    HOME="/root" \
    SHELL="/bin/bash" \
    TERM="xterm-256color" \
    SSH_CONNECTION="127.0.0.1 0 127.0.0.1 22" \
    PATH="/data/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

WORKDIR /homeassistant

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8099/ >/dev/null || exit 1

LABEL \
    org.opencontainers.image.title="Home Assistant Add-on: Antigravity CLI" \
    org.opencontainers.image.description="Google Antigravity autonomous AI agent CLI (agy) with persistent Remote Control daemon and Ingress web terminal" \
    org.opencontainers.image.source="https://github.com/morhimi/ha-antigravity-addon" \
    org.opencontainers.image.licenses="MIT"

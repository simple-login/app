ARG UV_VERSION=0.13.5
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM mcr.microsoft.com/devcontainers/python:3-3.12-bookworm

ARG NODE_VERSION=24

# Build deps for pyre2 / sl-pgp / PGP — deliberately NOT purged (unlike prod image).
# postgresql-client/redis-tools are for pg_isready/psql/redis-cli during debugging.
# Pre-create the volume mount points (~/.gnupg, ~/.cache/uv, ~/.local, /workspaces/simple-login-app/.venv)
# owned by vscode: a *fresh* named volume inherits this. It does NOT repair an
# already-existing root-owned volume.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
           /etc/apt/sources.list.d/yarn.sources \
 && apt-get update && apt-get install -y --no-install-recommends \
      git gnupg libpq-dev libre2-dev build-essential pkg-config \
      cmake ninja-build clang netcat-traditional swaks \
      postgresql-client redis-tools \
      procps \
 && mkdir -p /home/vscode/.gnupg /home/vscode/.cache/uv /home/vscode/.local/share/uv/python  \
             /home/vscode/.npm /workspaces/simple-login-app/.venv \
 && chown -R vscode:vscode /home/vscode/.gnupg /home/vscode/.cache /home/vscode/.local  \
             /home/vscode/.npm /workspaces/simple-login-app/.venv \
 && chmod 700 /home/vscode/.gnupg \
 && chmod 755 /home/vscode/.cache /home/vscode/.cache/uv \
 && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

# Node runtime for `npm ci` in static/. The base image ships nvm but no Node.
RUN bash -c 'export NVM_DIR=/usr/local/share/nvm \
      && . "$NVM_DIR/nvm.sh" \
      && nvm install "$NODE_VERSION" \
      && nvm alias default "$NODE_VERSION"' \
 && ln -sfn "/usr/local/share/nvm/versions/node/$(ls /usr/local/share/nvm/versions/node | sort -V | tail -1)" /usr/local/share/nvm/current \
 && ln -sf /usr/local/share/nvm/current/bin/node /usr/local/bin/node \
 && ln -sf /usr/local/share/nvm/current/bin/npm /usr/local/bin/npm \
 && node -v && npm -v

# Pin the cache path explicitly so it can never resolve somewhere unintended
# (e.g. /root/.cache/uv if the container is ever started as a different user).
ENV UV_PYTHON_INSTALL_DIR=/home/vscode/.local/share/uv/python \
    UV_CACHE_DIR=/home/vscode/.cache/uv \
    CMAKE_POLICY_VERSION_MINIMUM=3.5 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
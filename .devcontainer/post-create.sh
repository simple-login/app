#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# ---- credentials (must match .devcontainer/docker-compose.yml) -------------
PG_USER=myuser
PG_PASS=mypassword
PG_DB=simplelogin
PG_HOST=db
REDIS_URL=redis://redis:6379/0

DEV_DB_URI="postgresql://${PG_USER}:${PG_PASS}@${PG_HOST}:5432/${PG_DB}"

# ---- 1. .env: seed from example.env ----
[ -f .env ] || cp example.env .env

# set_env sets or REPLACES a key. Presence alone isn't enough — a stale value
# (e.g. GNUPGHOME=/home/simplelogin/.gnupg) is worse than a missing one because
# config.py only warns when GNUPGHOME is empty, not when it's wrong.
set_env() {
  if grep -q "^${1}=" .env; then
    sed -i "s|^${1}=.*|${1}=${2}|" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

set_env DB_URI         "$DEV_DB_URI"
set_env MEM_STORE_URI  "$REDIS_URL"
set_env GNUPGHOME      /home/vscode/.gnupg
set_env POSTFIX_SERVER localhost
set_env POSTFIX_PORT   1025

# presence alone disables sending
sed -i 's/^NOT_SEND_EMAIL=/# NOT_SEND_EMAIL=/' .env

# ---- 2. frontend assets ---------------------------------------------------
# templates/base.html pulls toastr/bootbox/htmx/font-awesome from
# static/node_modules, which is not committed. Upstream's prod Dockerfile runs
# `npm ci` there. Without it every /static/node_modules/* 404s and flash
# messages silently do nothing ("toastr is not defined").
bash .devcontainer/setup-frontend.sh

# named volume over a bind mount can end up root-owned; fix so uv sync can write
[ "$(stat -c %U .venv)" = vscode ] || sudo chown vscode:vscode .venv

# ---- 3. dependencies ------------------------------------------------------
# no --locked: this fork's uv.lock drifts from pyproject.toml.
uv sync
uv run pre-commit install || true

# ---- 4. dev database: schema + seed --------------------------------------
uv run alembic upgrade head          # NO '|| true' — must fail loudly

# dummy-data is NOT re-runnable (fixed emails -> unique violations), so guard it
if ! uv run python -c "from app.models import User; raise SystemExit(0 if User.get_by(email='john@wick.com') else 1)" >/dev/null 2>&1; then
  uv run flask dummy-data
fi

echo
echo "-------------------------------------------------------------"
echo " dev DB  : $DEV_DB_URI"
echo " redis   : $REDIS_URL"
echo " tests   : bash .devcontainer/run-tests.sh"
echo " frontend: bash .devcontainer/install-frontend.sh   (rerun after package-lock changes)"
echo " app     : uv run python server.py  -> http://localhost:7777"
echo "-------------------------------------------------------------"

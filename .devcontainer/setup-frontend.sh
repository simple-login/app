#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

STATIC_DIR=static

# The Dockerfile installs Node, so npm should already be on PATH.
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm not found. Rebuild the dev container; the Dockerfile installs Node." >&2
  exit 1
fi

echo "node $(node -v), npm $(npm -v)"

# Skip the install when package-lock.json has not changed since the last run.
# node_modules sits on the bind mount, so it survives container rebuilds.
STAMP="$STATIC_DIR/node_modules/.lock-hash"
LOCK_HASH="$(sha256sum "$STATIC_DIR/package-lock.json" | cut -d' ' -f1)"
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$LOCK_HASH" ]; then
  echo "frontend assets already installed (package-lock.json unchanged)"
  exit 0
fi

echo "installing frontend assets into $STATIC_DIR/node_modules"

# npm ci matches upstream's production Dockerfile. If the old v1 lockfile is
# rejected, fall back to npm install.
if ! ( cd "$STATIC_DIR" && npm ci --no-audit --no-fund --prefer-offline ); then
  echo "warning: npm ci failed, falling back to npm install (lockfile may drift)" >&2
  ( cd "$STATIC_DIR" && npm install --no-audit --no-fund --no-package-lock )
fi

# Check that the files the UI loads exist.
missing=0
for f in node_modules/toastr/build/toastr.min.js \
         node_modules/toastr/build/toastr.min.css \
         node_modules/bootbox/dist/bootbox.min.js \
         node_modules/htmx.org/dist/htmx.min.js \
         node_modules/font-awesome/css/font-awesome.css; do
  if [ ! -f "$STATIC_DIR/$f" ]; then
    echo "ERROR: $STATIC_DIR/$f missing after install" >&2
    missing=1
  fi
done
[ "$missing" -eq 0 ] || exit 1

printf '%s' "$LOCK_HASH" > "$STAMP"
echo "frontend assets OK"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# ---- config (must match .devcontainer/docker-compose.yml) -----------------
PG_USER=myuser
PG_PASS=mypassword
PG_HOST=db
PG_TEST_DB=simplelogin_test
PG_TEST_URI="postgresql://${PG_USER}:${PG_PASS}@${PG_HOST}:5432/${PG_TEST_DB}"
REDIS_URL=redis://redis:6379/1

# tests/conftest.py forces CONFIG=tests/test.env, which hardcodes localhost:15432
# and redis://localhost. config.py calls load_dotenv(..., override=False), so these
# exports win over the file.
export DB_URI="$PG_TEST_URI"
export MEM_STORE_URI="$REDIS_URL"
export PGPASSWORD="$PG_PASS"

# ---- 1. wait for services (bounded — don't hang the IDE forever) ---------
i=0
until pg_isready -h "$PG_HOST" -p 5432 -U "$PG_USER" -q; do
  i=$((i+1))
  if [ "$i" -ge 30 ]; then
    echo "ERROR: postgres not accepting connections at ${PG_HOST}:5432 after 60s" >&2
    exit 1
  fi
  echo "waiting for postgres..."; sleep 2
done

i=0
until [ "$(redis-cli -h redis ping 2>/dev/null || true)" = "PONG" ]; do
  i=$((i+1))
  if [ "$i" -ge 30 ]; then
    echo "ERROR: redis not reachable at ${REDIS_URL} after 60s" >&2
    exit 1
  fi
  echo "waiting for redis..."; sleep 2
done

# ---- 2. reset the test database (always) ---------------------------------
# Guard: this script DROPs a database unconditionally. Refuse anything that
# doesn't look like a test DB, so a typo in PG_TEST_DB can't wipe the dev database.
case "$PG_TEST_DB" in
  *test*) ;;
  *)
    echo "ERROR: refusing to DROP '${PG_TEST_DB}' — name does not contain 'test'." >&2
    echo "       check PG_TEST_DB in this script." >&2
    exit 1
    ;;
esac

echo "resetting ${PG_TEST_DB}"
psql -h "$PG_HOST" -U "$PG_USER" -d postgres -q \
  -c "DROP DATABASE IF EXISTS ${PG_TEST_DB} WITH (FORCE)"
psql -h "$PG_HOST" -U "$PG_USER" -d postgres -q \
  -c "CREATE DATABASE ${PG_TEST_DB} OWNER ${PG_USER}"

# ---- 3. migrate ----------------------------------------------------------
# conftest.py never calls create_all(), so the schema MUST come from migrations.
uv run alembic upgrade head

unset PGPASSWORD

# ---- 4. run pytest -------------------------------------------------------
if [ -f pytest.ci.ini ]; then
  exec uv run pytest -c pytest.ci.ini "$@"
else
  exec uv run pytest "$@"
fi

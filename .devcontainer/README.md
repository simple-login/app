# Dev Container

Development environment for simple-login-app: Python 3.12, uv, Node.js, Postgres, Redis and a local mail catcher, all wired together with Docker Compose.

Works with VS Code (Dev Containers extension) and JetBrains PyCharm (Dev Containers backend).

## What you get

| Service       | Image                   | Purpose                                                        |
|---------------|-------------------------|----------------------------------------------------------------|
| `app`         | built from `Dockerfile` | Your workspace (Python, uv, Node.js, build deps)               |
| `db`          | `postgres:18`           | Dev database `simplelogin` (+ `simplelogin_test` for tests)    |
| `redis`       | `redis:8`               | Dev uses DB `0`, tests use DB `1`                              |
| `mailcatcher` | `sj26/mailcatcher`      | Catches outgoing mail (SMTP `1025`, UI `1080`)                 |

Pinned tool versions are set in the `Dockerfile`:

| Tool    | Variable       | Default |
|---------|----------------|---------|
| uv      | `UV_VERSION`   | `0.13.5` |
| Node.js | `NODE_VERSION` | `24` (LTS) |

Forwarded ports:

| Port    | What                |
|---------|---------------------|
| `7777`  | Web app             |
| `20381` | Email handler SMTP  |
| `1080`  | MailCatcher UI      |

MailCatcher runs with `network_mode: "service:app"`, which means it lives inside the `app` container's network. That is why its UI port can be forwarded like any other port, and why the app reaches it at **`localhost:1025`** (not `mailcatcher:1025`).

Node.js is installed at image build time. It is used only to install the frontend libraries in `static/`. The base image ships nvm but no Node version, so the Dockerfile installs one.

## First start

1. Open the repo and choose **Reopen in Container** (VS Code) or open it via the Dev Containers backend (PyCharm).
2. Wait for `post-create.sh` to finish. It will:
   - create `.env` from `example.env` and set the container-correct values (`DB_URI`, `MEM_STORE_URI`, `GNUPGHOME`, `POSTFIX_SERVER=localhost`, `POSTFIX_PORT=1025`)
   - comment out `NOT_SEND_EMAIL` in `.env` (see [Mail doesn't arrive in MailCatcher](#mail-doesnt-arrive-in-mailcatcher))
   - install the frontend libraries into `static/node_modules` with `npm ci` (via `.devcontainer/install-frontend.sh`). They are not committed, and the UI needs them for toasts, dialogs, htmx and icons.
   - run `uv sync` and install the pre-commit hooks
   - run `alembic upgrade head` on the dev database
   - seed dummy data (once; the user `john@wick.com` is created by `flask dummy-data`)

The Python environment lives in `/workspaces/simple-login-app/.venv`. It is a named volume mounted over the repo's `.venv` directory, so it stays fast and never mixes with a `.venv` on your host machine. VS Code and PyCharm should detect it automatically.

If the IDE shows the wrong interpreter, or none, select `/workspaces/simple-login-app/.venv/bin/python` once. In VS Code this can happen on the very first build, because the environment is created after the window opens; **Developer: Reload Window** usually fixes it.

## Running the app

The container does not start the web server for you. Run it yourself:

```bash
uv run python server.py          # http://localhost:7777
uv run python email_handler.py   # email handler on port 20381 (only for email work)
```

Outgoing mail from the web app is delivered straight to MailCatcher. Open the UI on forwarded port `1080` to read it.

Configuration is read when a process starts, so **restart `server.py` after any change to `.env`**.

## Running tests

**Always run tests through the script:**

```bash
bash .devcontainer/run-tests.sh                       # whole suite
bash .devcontainer/run-tests.sh tests/test_foo.py -k bar   # extra args go to pytest
```

The script waits for Postgres and Redis, (re)creates the `simplelogin_test` database, applies migrations, points the app at the test database and Redis DB `1`, and then runs pytest.

The test database is dropped and rebuilt (including all migrations) on every run, so each run starts from a clean state. This is safe but adds some startup time, even when you run a single test.

### Why the IDE test runner doesn't work out of the box

This is intentional, not a bug.

The container does **not** set `DB_URI`, so that nothing can accidentally run tests against your dev data. `tests/conftest.py` forces `CONFIG=tests/test.env`, which points at `localhost:15432`. A pytest started from the VS Code Testing panel, a PyCharm run configuration, or a bare `uv run pytest` therefore can't reach a database and fails to connect.

The VS Code Testing panel is disabled in this container (`python.testing.pytestEnabled: false`). If you enable it, test discovery will fail with database connection errors; use `run-tests.sh` instead.

## Day-to-day notes

- **Commit from inside the container.** The pre-commit hook points at the container's virtualenv, so committing from the host fails with "pre-commit not found".
- **After `git pull`**, new migrations are applied automatically the next time the container starts. If you pulled while it was running, run `uv run alembic upgrade head` yourself.
- **After `git pull`, if `static/package-lock.json` changed**, run `bash .devcontainer/install-frontend.sh`. It is a fast no-op when the lockfile is unchanged.
- **`static/node_modules/` must stay gitignored.** It is installed, not vendored.
- **An empty `.venv` directory appears in the repo on your host.** It is the mount point for the virtualenv volume and should be gitignored. Don't delete it while the container is running.

## Resetting things

Stop the stack first:

```bash
docker compose -p simplelogin-devcontainer down
```

Then remove only what you need to reset:

```bash
# dev database (re-seeded on next container creation)
docker volume rm simplelogin-devcontainer_pgdata

# Python environment
docker volume rm simplelogin-devcontainer_venv

# uv cache, uv-managed Pythons, GPG keys
docker volume rm simplelogin-devcontainer_uv-cache \
                 simplelogin-devcontainer_uv-python \
                 simplelogin-devcontainer_gnupg
```

Or remove everything, including the dev database:

```bash
docker compose -p simplelogin-devcontainer down -v
```

Then use **Dev Containers: Rebuild Container**.

Frontend libraries live in `static/node_modules` on the bind mount, so they survive these resets. To reinstall them, run `rm -rf static/node_modules && bash .devcontainer/install-frontend.sh`.

### Permission errors on `~/.cache/uv`, `~/.gnupg` or `~/.local`

New volumes inherit the correct ownership from the image, but a volume created by an older version of this setup may still be owned by root, and Docker never repairs existing volumes. Remove the affected volume (see above) and rebuild.

The `.venv` volume is the exception: `post-create.sh` checks its ownership on every run and repairs it if needed.

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| Container fails to start with "dependency failed to start" | `db` or `redis` never became healthy. Check `docker compose -p simplelogin-devcontainer logs db`. |
| `localhost:7777` says "connection reset" | The web server isn't running. Start it with `uv run python server.py`. |
| Tests fail with connection refused on `localhost:15432` | You ran pytest directly. Use `run-tests.sh`. |
| `git status` shows a modified `uv.lock` | Expected: `uv sync` rewrites the drifting lockfile. Don't commit it unless you changed dependencies. |
| Saving a form shows no confirmation toast; "toastr is not defined" in the console; 404s for `/static/node_modules/…` | Frontend libraries not installed. Run `bash .devcontainer/install-frontend.sh`. |
| Mail from the app doesn't show up | See [Mail doesn't arrive in MailCatcher](#mail-doesnt-arrive-in-mailcatcher). |
| MailCatcher UI on port `1080` doesn't open | MailCatcher shares the `app` container's network. Restart it (see below), and check that nothing else in the container is using port `1080`. |
| Wrong or missing interpreter in the IDE | Select `/workspaces/simple-login-app/.venv/bin/python`. In VS Code, **Developer: Reload Window** after the first build usually fixes it. |
| `uv sync` tries to download Python 3.15 | No Python is pinned. Run `uv python pin 3.12` and commit `.python-version`. |

### Mail doesn't arrive in MailCatcher

Check these in order:

1. **`NOT_SEND_EMAIL` must not be set at all in `.env`.** The app only checks whether the variable exists, so even `NOT_SEND_EMAIL=false` disables sending. The upstream `example.env` sets it to `true`; `post-create.sh` comments it out. Verify with:
   ```bash
   uv run python -c "from app import config; print(config.NOT_SEND_EMAIL)"   # must print False
   env | grep NOT_SEND_EMAIL                                                # must print nothing
   ```
2. **`POSTFIX_SERVER=localhost` and `POSTFIX_PORT=1025`** in `.env`. Use `localhost`, not `mailcatcher`: MailCatcher shares the app container's network, so the hostname `mailcatcher` does not resolve.
3. **Restart `server.py`** after changing `.env`.
4. **Test MailCatcher on its own** (`swaks` is installed in the image):
   ```bash
   swaks --to test@example.com --from dev@example.com --server localhost --port 1025
   ```
   If that message appears at `http://localhost:1080`, MailCatcher is fine, and the problem is the app's configuration. If it reports connection refused, MailCatcher isn't running in the app's network; restart it:
   ```bash
   docker compose -p simplelogin-devcontainer restart mailcatcher
   ```
   Because MailCatcher is attached to the `app` container's network, it may need a restart whenever the `app` container is recreated.

## Credentials

The database and Redis credentials are for local development only and are duplicated in `docker-compose.yml`, `post-create.sh` and `run-tests.sh`. If you change one, change all three. No service publishes a port on the host: `db` and `redis` are reachable only on the Compose network, and the web app and MailCatcher UI are reached through the IDE's port forwarding.

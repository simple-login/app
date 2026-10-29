# Commands

- Install: `uv sync` (CI: `uv sync --locked --all-extras`). Mac native deps: `brew install pkg-config libffi openssl postgresql@13 gnupg`; pyre2 may need `brew install -s re2 pybind11`.
- Tests (full, dockerised DB): `sh scripts/run-test.sh` — starts postgres:13 on :15432 (`test:test@localhost:15432/test`), runs migrations, `uv run pytest -c pytest.ci.ini` (with coverage).
- Tests against an existing DB: `CONFIG=tests/test.env uv run alembic upgrade head` once, then `uv run pytest tests/path/test_x.py::test_name`. DB URI comes from `tests/test.env` (`DB_URI`). Reset: `scripts/reset_test_db.sh`.
- Lint/format: `uv run pre-commit run --all-files` (ruff --fix, ruff-format, djlint reformat for .html, yaml/whitespace). Single file: `uv run ruff check --fix <f> && uv run ruff format <f>`.
- New migration: `sh scripts/new-migration.sh` (Docker). Apply: `uv run alembic upgrade head`.
- Run locally: `cp example.env .env`, `alembic upgrade head && flask dummy-data && python3 server.py` -> http://localhost:7777, login `john@wick.com / password`. Local dev DB reset: `scripts/reset_local_db.sh`.
- Proto regen: `scripts/generate-proto-files.sh`.
- Darwin: BSD `sed` (`sed -i ''`), no GNU `timeout` by default.

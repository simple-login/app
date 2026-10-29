# Task completion

1. `uv run ruff check --fix <changed files> && uv run ruff format <changed files>` (or `uv run pre-commit run --all-files`; djlint also reformats changed `.html` templates).
2. Run relevant tests: `uv run pytest tests/<area>` (needs migrated test DB + Redis, see `mem:suggested_commands`). CI runs the full `uv run pytest`.
3. Model change -> alembic migration added and reviewed in `migrations/`.
4. No type checker in CI.

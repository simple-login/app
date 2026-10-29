# Conventions

## DB / models
- `ModelMixin` classmethods: `X.create(..., commit=False, flush=False)`, `X.get(id)`, `X.get_by(**kw)`, `X.filter_by(...)`, `X.delete(id, commit=False)`. Default is no commit — callers commit via `Session.commit()` (import `from app.db import Session`).
- Prefer `flush=True` when an id is needed before commit; utils typically take a `commit: bool = False` param and let the caller decide.
- Raw `Session.query(...)` legacy API (SQLAlchemy 1.3).
- Security-relevant user/alias changes should emit audit logs via `emit_user_audit_log(user, UserAuditLogAction.X, message)` / `emit_alias_audit_log(...)`.

## Code style
- ruff lint + ruff-format (black-compatible). Type hints used on new code, not universally.
- Logging: `from app.log import LOG`; `LOG.i/.d/.w/.e(...)` short-form methods common.
- Config: add settings as module-level constants in `app/config.py` read from `os.environ`; boolean flags parsed manually from strings.
- Business logic in `app/*_utils.py`; views thin.

## Tests
- `tests/conftest.py` sets `CONFIG=tests/test.env`, binds `Session` to one shared connection; `flask_client` fixture wraps each test in an outer transaction and rolls back (commits inside tests are safe). CSRF disabled, `SERVER_NAME=sl.lan`, rate limiting disabled.
- Helpers in `tests/utils.py`: `create_new_user()`, `login(flask_client, user=None)`, `enter_sudo_mode`, `random_email`/`random_token`, etc.
- Test layout mirrors `app/` (`tests/api`, `tests/dashboard`, ...); flat `tests/test_<module>.py` for flat utils modules.
- Example emails for handler tests in `tests/example_emls/`.

# Tech stack

- Python `~=3.12` (`.python-version` 3.12.8); deps managed by **uv** (`uv.lock` authoritative; `poetry.lock`/`requirements*.lock` are legacy leftovers).
- Old pinned framework versions — don't assume modern APIs:
  - Flask 1.1, Werkzeug 1.0, itsdangerous 1.1, MarkupSafe 1.1, WTForms 2.3, Flask-WTF 0.14, Flask-Login 0.5, flask_admin 1.5, Flask-Limiter 1.5.
  - **SQLAlchemy 1.3** (legacy `Query` API, no 2.0-style `select()` sessions, `conn.execute("raw sql")` works), alembic 1.4.
  - pytest 7.0, ruff 0.1.5 (pre-commit pinned), black 22 (legacy, ruff-format is what runs).
- Postgres 13+ (needs `pg_trgm` extension), Redis (sessions, rate limiting; tests need it on 6379).
- `sl-pgp` comes from sl-pgp-rs wheels via `[tool.uv] find-links`.
- Templates: Jinja, linted/reformatted by djlint (`[tool.djlint]` in pyproject). Frontend assets in `static/` (npm).
- Monitoring: Sentry, New Relic. Build: hatchling, `Dockerfile`.

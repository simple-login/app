# SimpleLogin app — core

Email alias/forwarding service (Flask monolith). Stack/versions: `mem:tech_stack`. Commands: `mem:suggested_commands`. Style/patterns: `mem:conventions`. Done-checklist: `mem:task_completion`.

## Entry points (repo root)
- `server.py` (`create_app`, dev server :7777) / `wsgi.py` — webapp. Prod: gunicorn sync workers, single-threaded.
- `email_handler.py` — aiosmtpd forwarding/reverse-alias handler; logic in `app/handler/`, `app/email_utils.py`.
- `cron.py` + `crontab.yml` — scheduled jobs; `tasks/` holds cron task modules.
- `job_runner.py` — DB-backed async jobs; job impls in `app/jobs/`.
- `event_listener.py` + `events/` — event sink/source runner; protobuf schema `proto/event.proto` -> generated `app/events/generated/` (regen: `scripts/generate-proto-files.sh`; never hand-edit, excluded from lint).
- `monitoring.py`, `init_app.py` (seeds SL domains / Proton partner), `shell.py`.

## Source map (`app/`)
- `models.py` — ALL SQLAlchemy models (huge; `User` class alone ~900 lines). `oauth_models.py`, `pw_models.py` supplementary.
- `db.py` — engine + `Session` (scoped_session, bound to engine).
- `config.py` — every setting read from env at import time (`CONFIG` env var points to the .env file).
- Blueprints: `api/views/` (REST API for extensions/mobile), `dashboard/`, `auth/`, `oauth/` (SL as OIDC provider), `developer/`, `admin/` (flask_admin), `internal/`, `onboarding/`, `phone/`, `discover/`, `monitor/`.
- Domain logic lives in flat `*_utils.py` modules (alias_utils, mailbox_utils, custom_domain_utils, ...), not in views.
- Audit logs: `user_audit_log_utils.py`, `alias_audit_log_utils.py`, `abuser_audit_log_utils.py` (emit_* helpers).
- `session.py` — custom Redis-backed Flask session interface + sudo-mode helpers.
- `proton/` — Proton account linking/partner integration; `payments/`, `paddle_*` — billing.

## Invariants
- Schema changes need an alembic migration in `migrations/` (generated via `scripts/new-migration.sh`, needs Docker). Local dev DB uses `db.create_all()` (fake_data) so it can't generate migrations.
- `migrations/`, `static/node_modules|assets|vendor` excluded from lint/format.

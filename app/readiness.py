import hmac
from typing import Callable, Optional

from flask import Blueprint, Flask, current_app, jsonify, request
from sqlalchemy import text

from app import config
from app.db import Session
from app.log import LOG
from app.redis_services import REDIS_STORAGE_EXTENSION

READINESS_PATH = "/health/ready"
_BEARER_PREFIX = "Bearer "

CHECK_OK = "ok"
CHECK_FAIL = "fail"
CHECK_DISABLED = "disabled"


def is_auth_valid(authorization_header: Optional[str]) -> bool:
    expected = config.READINESS_TOKEN
    if not expected or not authorization_header:
        return False
    if not authorization_header.startswith(_BEARER_PREFIX):
        return False
    provided = authorization_header[len(_BEARER_PREFIX) :]
    return hmac.compare_digest(provided.encode(), expected.encode())


def check_database() -> str:
    Session.execute(text("SELECT 1"))
    return CHECK_OK


def check_redis() -> str:
    storage = current_app.extensions.get(REDIS_STORAGE_EXTENSION)
    if storage is None:
        return CHECK_DISABLED
    if not storage.storage.ping():
        raise RuntimeError("redis ping returned a falsy reply")
    return CHECK_OK


CHECKS: dict[str, Callable[[], str]] = {
    "database": check_database,
    "redis": check_redis,
}


def run_checks() -> dict[str, str]:
    results = {}
    for name, check in CHECKS.items():
        try:
            results[name] = check()
        except Exception as e:
            LOG.w("readiness check %s failed: %s", name, e)
            results[name] = CHECK_FAIL
    return results


def create_readiness_blueprint() -> Optional[Blueprint]:
    if not config.READINESS_TOKEN:
        LOG.w(
            "READINESS_TOKEN is empty: the %s endpoint stays disabled", READINESS_PATH
        )
        return None

    blueprint = Blueprint("readiness", __name__)

    @blueprint.route(READINESS_PATH, methods=["GET"])
    def readiness():
        if not is_auth_valid(request.headers.get("Authorization")):
            return "", 401, {"WWW-Authenticate": 'Bearer realm="readiness"'}

        checks = run_checks()
        ready = all(result != CHECK_FAIL for result in checks.values())
        body = {"status": CHECK_OK if ready else CHECK_FAIL, "checks": checks}
        return jsonify(body), 200 if ready else 503

    return blueprint


def setup_readiness(app: Flask) -> None:
    blueprint = create_readiness_blueprint()
    if blueprint is not None:
        app.register_blueprint(blueprint)

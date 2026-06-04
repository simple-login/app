from app import config
from app.config import EMAIL_DOMAIN


def test_redirect_login_page(flask_client):
    """Start with a blank database."""

    rv = flask_client.get("/")
    assert rv.status_code == 302
    assert rv.location == f"http://{EMAIL_DOMAIN}/auth/login"


def test_maintenance_mode_blocks_web_routes(flask_client):
    original = config.MAINTENANCE_MODE
    config.MAINTENANCE_MODE = True
    try:
        rv = flask_client.get("/")
        assert rv.status_code == 503
        assert b"503" in rv.data
    finally:
        config.MAINTENANCE_MODE = original


def test_maintenance_mode_blocks_api_routes(flask_client):
    original = config.MAINTENANCE_MODE
    config.MAINTENANCE_MODE = True
    try:
        rv = flask_client.get("/api/user_info")
        assert rv.status_code == 503
        assert rv.is_json
        assert "error" in rv.get_json()
    finally:
        config.MAINTENANCE_MODE = original


def test_maintenance_mode_allows_health_check(flask_client):
    original = config.MAINTENANCE_MODE
    config.MAINTENANCE_MODE = True
    try:
        rv = flask_client.get("/health")
        assert rv.status_code == 200
    finally:
        config.MAINTENANCE_MODE = original


def test_maintenance_mode_disabled_serves_normally(flask_client):
    original = config.MAINTENANCE_MODE
    config.MAINTENANCE_MODE = False
    try:
        rv = flask_client.get("/")
        assert rv.status_code == 302
    finally:
        config.MAINTENANCE_MODE = original

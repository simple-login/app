import pytest

from tests.conftest import app


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "enable_flask_wtf_csrf: run this test with Flask-WTF CSRF validation on",
    )


@pytest.fixture
def csrf_off():
    """Pin CSRF validation off for the duration of a sign-in.

    The suite disables CSRF globally (tests/conftest.py); pinning it here means
    a login cannot be sabotaged by whatever ran before it.
    """
    with _csrf_enabled(False):
        yield


@pytest.fixture
def enable_flask_wtf_csrf():
    """Turn Flask-WTF CSRF validation back on for one test.

    Without this the suite-wide default would make every CSRF-enforcement
    assertion pass vacuously. A login attempted with validation on does not
    fail loudly - it just re-renders the login page - so sign in first, and
    request this fixture after the sign-in one: pytest tears fixtures down in
    reverse order of setup, so the flag flips on once the login is done.
    """
    with _csrf_enabled(True):
        yield


class _csrf_enabled:
    """Context manager restoring the previous ``WTF_CSRF_ENABLED`` on exit."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __enter__(self):
        self.previous = app.config.get("WTF_CSRF_ENABLED")
        app.config["WTF_CSRF_ENABLED"] = self.enabled
        return self

    def __exit__(self, *exc_info):
        app.config["WTF_CSRF_ENABLED"] = self.previous
        return False

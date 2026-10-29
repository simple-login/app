import pytest

from app import metrics
from app.config import EMAIL_DOMAIN
from tests.metrics.utils import RecorderBackend


def test_redirect_login_page(flask_client):
    """Start with a blank database."""

    rv = flask_client.get("/")
    assert rv.status_code == 302
    assert rv.location == f"http://{EMAIL_DOMAIN}/auth/login"


@pytest.fixture
def recorded_events():
    recorder = RecorderBackend()
    metrics.configure([recorder])
    yield recorder.events
    metrics.reset()


def http_statuses(events) -> list:
    return [attrs["code"] for name, attrs in events if name == "HttpResponseStatus"]


@pytest.mark.parametrize(
    "path", ["/health", "/static/favicon.ico", "/admin/static/x.css", "/metrics"]
)
def test_infrastructure_requests_are_not_counted(flask_client, recorded_events, path):
    flask_client.get(path)

    assert http_statuses(recorded_events) == []


def test_page_requests_are_counted(flask_client, recorded_events):
    flask_client.get("/")

    assert http_statuses(recorded_events) == [302]

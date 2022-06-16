from http import HTTPStatus
from app.onboarding.utils import CHROME_EXTENSION_LINK


CHROME_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36"


def test_extension_redirect_is_working(flask_client):
    res = flask_client.get(
        "/onboarding/extension_redirect", headers={"User-Agent": CHROME_USER_AGENT}
    )
    assert res.status_code == HTTPStatus.FOUND

    location_header = res.headers.get("Location")
    assert location_header == CHROME_EXTENSION_LINK

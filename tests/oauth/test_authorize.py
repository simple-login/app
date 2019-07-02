from app.oauth.views.authorize import (
    get_host_name_and_scheme,
    generate_access_token,
    construct_url,
)


def test_get_host_name_and_scheme():
    assert get_host_name_and_scheme("http://localhost:8000?a=b") == (
        "localhost",
        "http",
    )

    assert get_host_name_and_scheme(
        "https://www.bubblecode.net/en/2016/01/22/understanding-oauth2/#Implicit_Grant"
    ) == ("www.bubblecode.net", "https")


def test_generate_access_token(flask_client):
    access_token = generate_access_token()
    assert len(access_token) == 40


def test_construct_url():
    url = construct_url("http://ab.cd", {"x": "1 2"})
    assert url == "http://ab.cd?x=1%202"

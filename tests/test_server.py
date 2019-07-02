def test_redirect_login_page(flask_client):
    """Start with a blank database."""

    rv = flask_client.get("/")
    assert rv.status_code == 302
    assert rv.location == "http://localhost/auth/login"

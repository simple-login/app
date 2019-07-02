import flask
import pytest

from app.oauth_models import get_scopes, ScopeE, get_response_types, ResponseType


def test_get_scopes(flask_app):
    with flask_app.test_request_context("/"):
        scopes = get_scopes(flask.request)
        assert scopes == set()

    with flask_app.test_request_context("/?scope=email&scope=name"):
        scopes = get_scopes(flask.request)
        assert scopes == {ScopeE.NAME, ScopeE.EMAIL}

    # a space between email and name
    with flask_app.test_request_context("/?scope=email%20name"):
        scopes = get_scopes(flask.request)
        assert scopes == {ScopeE.NAME, ScopeE.EMAIL}

    # a comma between email and name
    with flask_app.test_request_context("/?scope=email,name"):
        scopes = get_scopes(flask.request)
        assert scopes == {ScopeE.NAME, ScopeE.EMAIL}

    # non-existent scope: raise ValueError
    with flask_app.test_request_context("/?scope=abcd"):
        with pytest.raises(ValueError):
            get_scopes(flask.request)


def test_get_response_types(flask_app):
    with flask_app.test_request_context("/"):
        response_types = get_response_types(flask.request)
        assert response_types == set()

    with flask_app.test_request_context("/?response_type=token&response_type=id_token"):
        response_types = get_response_types(flask.request)
        assert response_types == {ResponseType.TOKEN, ResponseType.ID_TOKEN}

    # a space as separator
    with flask_app.test_request_context("/?response_type=token%20id_token"):
        response_types = get_response_types(flask.request)
        assert response_types == {ResponseType.TOKEN, ResponseType.ID_TOKEN}

    # a comma as separator
    with flask_app.test_request_context("/?response_type=id_token,token"):
        response_types = get_response_types(flask.request)
        assert response_types == {ResponseType.TOKEN, ResponseType.ID_TOKEN}

    # non-existent response_type: raise ValueError
    with flask_app.test_request_context("/?response_type=abcd"):
        with pytest.raises(ValueError):
            get_response_types(flask.request)

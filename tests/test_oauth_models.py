import flask
import pytest

from app.oauth_models import (
    get_scopes,
    Scope,
    get_response_types,
    ResponseType,
    response_types_to_str,
    get_response_types_from_str,
)


def test_get_scopes(flask_app):
    with flask_app.test_request_context("/"):
        scopes = get_scopes(flask.request)
        assert scopes == set()

    with flask_app.test_request_context("/?scope=email&scope=name"):
        scopes = get_scopes(flask.request)
        assert scopes == {Scope.NAME, Scope.EMAIL}

    # a space between email and name
    with flask_app.test_request_context("/?scope=email%20name"):
        scopes = get_scopes(flask.request)
        assert scopes == {Scope.NAME, Scope.EMAIL}

    # a comma between email and name
    with flask_app.test_request_context("/?scope=email,name"):
        scopes = get_scopes(flask.request)
        assert scopes == {Scope.NAME, Scope.EMAIL}

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


def test_response_types_to_str():
    assert response_types_to_str([]) == ""
    assert response_types_to_str([ResponseType.CODE]) == "code"
    assert (
        response_types_to_str([ResponseType.CODE, ResponseType.ID_TOKEN])
        == "code,id_token"
    )


def test_get_response_types_from_str():
    assert get_response_types_from_str("") == set()
    assert get_response_types_from_str("token") == {ResponseType.TOKEN}
    assert get_response_types_from_str("token id_token") == {
        ResponseType.TOKEN,
        ResponseType.ID_TOKEN,
    }

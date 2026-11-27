"""Keep behaviours the app (and its API clients) relied on under Flask 1.x."""

from typing import Any, Optional

import flask
from flask.json.provider import DefaultJSONProvider

from app.user_agent import ParsedUserAgent


class SLJSONProvider(DefaultJSONProvider):
    """Flask 1 serialized JSON with simplejson when installed, which encodes
    bytes as UTF-8 strings. Flask >= 2.2 always uses the stdlib json module."""

    @staticmethod
    def default(o: Any) -> Any:
        if isinstance(o, bytes):
            return o.decode()
        return DefaultJSONProvider.default(o)


class SLRequest(flask.Request):
    """Since Flask 2.1, request.get_json() fails with 415 Unsupported Media Type
    when the request does not have a JSON content type. Before, it returned None,
    and many endpoints (e.g. a DELETE without body) rely on that.

    Werkzeug >= 2.1 also stopped parsing the user agent: plug our own parser."""

    user_agent_class = ParsedUserAgent

    def on_json_loading_failed(self, e: Optional[ValueError]) -> Any:
        if e is None:
            return None
        return super().on_json_loading_failed(e)


class SLResponse(flask.Response):
    """Werkzeug >= 2.1 sends relative Location headers. Keep sending absolute
    ones, as before, for API and OAuth clients that may rely on it."""

    autocorrect_location_header = True


def apply_flask_compat(app: flask.Flask):
    app.json = SLJSONProvider(app)
    app.request_class = SLRequest
    app.response_class = SLResponse

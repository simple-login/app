from typing import Optional

from sentry_sdk.types import Event, Hint

_HTTP_CODES_TO_IGNORE = [416]


def _should_send(_event: Event, hint: Hint) -> bool:
    # Check if this is an HTTP Exception event
    if "exc_info" in hint:
        exc_type, exc_value, exc_traceback = hint["exc_info"]
        # Check if it's a Werkzeug HTTPException (raised for HTTP status codes)
        if hasattr(exc_value, "code") and exc_value.code in _HTTP_CODES_TO_IGNORE:
            return False
    return True


def sentry_before_send(event: Event, hint: Hint) -> Optional[Event]:
    if _should_send(event, hint):
        return event
    return None

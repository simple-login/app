from unittest import mock

from events import event_sink
from events.event_sink import HttpEventSink


def _post_response(status_code: int = 200) -> mock.Mock:
    res = mock.Mock()
    res.status_code = status_code
    res.text = ""
    return res


def test_webhook_request_includes_token_header_when_configured(monkeypatch):
    monkeypatch.setattr(event_sink, "EVENT_WEBHOOK", "http://test")
    monkeypatch.setattr(event_sink, "EVENT_WEBHOOK_TOKEN", "secret-token")

    with mock.patch.object(
        event_sink.requests, "post", return_value=_post_response()
    ) as post:
        assert HttpEventSink().send_data_to_webhook(b"data")

    headers = post.call_args.kwargs["headers"]
    assert headers["authorization"] == "Bearer secret-token"
    assert headers["Content-Type"] == "application/x-protobuf"


def test_webhook_request_omits_token_header_when_not_configured(monkeypatch):
    monkeypatch.setattr(event_sink, "EVENT_WEBHOOK", "http://test")
    monkeypatch.setattr(event_sink, "EVENT_WEBHOOK_TOKEN", None)

    with mock.patch.object(
        event_sink.requests, "post", return_value=_post_response()
    ) as post:
        assert HttpEventSink().send_data_to_webhook(b"data")

    headers = post.call_args.kwargs["headers"]
    assert "authorization" not in headers
    assert headers == {"Content-Type": "application/x-protobuf"}

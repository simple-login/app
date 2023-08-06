import http.server
import json
import threading

import arrow

from app import config
from app.models import (
    Subscription,
    AppleSubscription,
    CoinbaseSubscription,
    ManualSubscription,
)
from tests.utils import create_new_user, random_token

from app.subscription_webhook import execute_subscription_webhook

http_server = None
last_http_request = None


def setup_module():
    global http_server
    http_server = http.server.ThreadingHTTPServer(("", 0), HTTPTestServer)
    print(http_server.server_port)
    threading.Thread(target=http_server.serve_forever, daemon=True).start()
    config.SUBSCRIPTION_CHANGE_WEBHOOK = f"http://localhost:{http_server.server_port}"


def teardown_module():
    global http_server
    config.SUBSCRIPTION_CHANGE_WEBHOOK = None
    http_server.shutdown()


class HTTPTestServer(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        global last_http_request
        content_len = int(self.headers.get("Content-Length"))
        body_data = self.rfile.read(content_len)
        last_http_request = json.loads(body_data)
        self.send_response(200)


def test_webhook_with_trial():
    user = create_new_user()
    execute_subscription_webhook(user)
    assert last_http_request["user_id"] == user.id
    assert last_http_request["is_premium"]
    assert last_http_request["active_subscription_end"] is None


def test_webhook_with_subscription():
    user = create_new_user()
    end_at = arrow.utcnow().shift(days=1).replace(hour=0, minute=0, second=0)
    Subscription.create(
        user_id=user.id,
        cancel_url="",
        update_url="",
        subscription_id=random_token(10),
        event_time=arrow.now(),
        next_bill_date=end_at.date(),
        plan="yearly",
        flush=True,
    )
    execute_subscription_webhook(user)
    assert last_http_request["user_id"] == user.id
    assert last_http_request["is_premium"]
    assert last_http_request["active_subscription_end"] == end_at.timestamp


def test_webhook_with_apple_subscription():
    user = create_new_user()
    end_at = arrow.utcnow().shift(days=2).replace(hour=0, minute=0, second=0)
    AppleSubscription.create(
        user_id=user.id,
        receipt_data=arrow.now().date().strftime("%Y-%m-%d"),
        expires_date=end_at.date().strftime("%Y-%m-%d"),
        original_transaction_id=random_token(10),
        plan="yearly",
        product_id="",
        flush=True,
    )
    execute_subscription_webhook(user)
    assert last_http_request["user_id"] == user.id
    assert last_http_request["is_premium"]
    assert last_http_request["active_subscription_end"] == end_at.timestamp


def test_webhook_with_coinbase_subscription():
    user = create_new_user()
    end_at = arrow.utcnow().shift(days=3).replace(hour=0, minute=0, second=0)
    CoinbaseSubscription.create(
        user_id=user.id, end_at=end_at.date().strftime("%Y-%m-%d"), flush=True
    )

    execute_subscription_webhook(user)
    assert last_http_request["user_id"] == user.id
    assert last_http_request["is_premium"]
    assert last_http_request["active_subscription_end"] == end_at.timestamp


def test_webhook_with_manual_subscription():
    user = create_new_user()
    end_at = arrow.utcnow().shift(days=3).replace(hour=0, minute=0, second=0)
    ManualSubscription.create(
        user_id=user.id, end_at=end_at.date().strftime("%Y-%m-%d"), flush=True
    )

    execute_subscription_webhook(user)
    assert last_http_request["user_id"] == user.id
    assert last_http_request["is_premium"]
    assert last_http_request["active_subscription_end"] == end_at.timestamp

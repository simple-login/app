from typing import Optional

import arrow
from coinbase_commerce.error import WebhookInvalidPayload, SignatureVerificationError
from coinbase_commerce.webhook import Webhook
from flask import Flask, request

from app.config import COINBASE_WEBHOOK_SECRET
from app.db import Session
from app.email_utils import send_email, render
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
from app.log import LOG
from app.models import CoinbaseSubscription, User
from app.subscription_webhook import execute_subscription_webhook
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


def setup_coinbase_commerce(app: Flask):
    @app.route("/coinbase", methods=["POST"])
    def coinbase_webhook():
        # event payload
        request_data = request.data.decode("utf-8")
        # webhook signature
        request_sig = request.headers.get("X-CC-Webhook-Signature", None)

        try:
            # signature verification and event object construction
            event = Webhook.construct_event(
                request_data, request_sig, COINBASE_WEBHOOK_SECRET
            )
        except (WebhookInvalidPayload, SignatureVerificationError) as e:
            LOG.e("Invalid Coinbase webhook")
            return str(e), 400

        LOG.d("Coinbase event %s", event)

        if event["type"] == "charge:confirmed":
            if handle_coinbase_event(event):
                return "success", 200
            else:
                return "error", 400

        return "success", 200


def handle_coinbase_event(event) -> bool:
    server_user_id = event["data"]["metadata"]["user_id"]
    try:
        user_id = int(server_user_id)
    except ValueError:
        user_id = int(float(server_user_id))

    code: str = event["data"]["code"]
    user: Optional[User] = User.get(user_id)
    if not user:
        LOG.e("User not found %s", user_id)
        return False

    create_coinbase_subscription(user, code)
    return True


def create_coinbase_subscription(user: User, code: str) -> CoinbaseSubscription:
    coinbase_subscription: CoinbaseSubscription = CoinbaseSubscription.get_by(
        user_id=user.id
    )
    if not coinbase_subscription:
        LOG.d("Create a coinbase subscription for %s", user)
        coinbase_subscription = CoinbaseSubscription.create(
            user_id=user.id, end_at=arrow.now().shift(years=1), code=code, commit=True
        )
        emit_user_audit_log(
            user=user,
            action=UserAuditLogAction.Upgrade,
            message="Upgraded though Coinbase",
            commit=True,
        )

        send_email(
            user.email,
            "Your SimpleLogin account has been upgraded",
            render(
                "transactional/coinbase/new-subscription.txt",
                user=user,
                coinbase_subscription=coinbase_subscription,
            ),
            render(
                "transactional/coinbase/new-subscription.html",
                user=user,
                coinbase_subscription=coinbase_subscription,
            ),
        )
    else:
        if coinbase_subscription.code != code:
            LOG.d("Update code from %s to %s", coinbase_subscription.code, code)
            coinbase_subscription.code = code

        if coinbase_subscription.is_active():
            coinbase_subscription.end_at = coinbase_subscription.end_at.shift(years=1)
        else:  # already expired subscription
            coinbase_subscription.end_at = arrow.now().shift(years=1)

        emit_user_audit_log(
            user=user,
            action=UserAuditLogAction.SubscriptionExtended,
            message="Extended coinbase subscription",
        )

        send_email(
            user.email,
            "Your SimpleLogin account has been extended",
            render(
                "transactional/coinbase/extend-subscription.txt",
                user=user,
                coinbase_subscription=coinbase_subscription,
            ),
            render(
                "transactional/coinbase/extend-subscription.html",
                user=user,
                coinbase_subscription=coinbase_subscription,
            ),
        )
    EventDispatcher.send_event(
        user=user,
        content=EventContent(
            user_plan_change=UserPlanChanged(
                plan_end_time=coinbase_subscription.end_at.timestamp
            )
        ),
    )
    Session.commit()
    execute_subscription_webhook(user)
    return coinbase_subscription

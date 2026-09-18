import arrow
from dateutil.relativedelta import relativedelta
from flask import Flask, request

from app import paddle_utils, paddle_callback
from app.config import (
    PADDLE_MONTHLY_PRODUCT_ID,
    PADDLE_MONTHLY_PRODUCT_IDS,
    PADDLE_YEARLY_PRODUCT_IDS,
    PADDLE_COUPON_ID,
)
from app.db import Session
from app.email_utils import send_email, render
from app.log import LOG
from app.models import Subscription, PlanEnum, User, Coupon
from app.payments.paddle_passthrough import verify_passthrough
from app.subscription_webhook import execute_subscription_webhook
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.utils import random_string


def setup_paddle_callback(app: Flask):
    @app.route("/paddle", methods=["GET", "POST"])
    def paddle():
        LOG.d(f"paddle callback {request.form.get('alert_name')} {request.form}")

        # make sure the request comes from Paddle
        if not paddle_utils.verify_incoming_request(dict(request.form)):
            LOG.e("request not coming from paddle. Request data:%s", dict(request.form))
            return "KO", 400

        if (
            request.form.get("alert_name") == "subscription_created"
        ):  # new user subscribes
            # the passthrough is set by the browser when opening the checkout,
            # only trust it if it carries our own signature
            user_id = verify_passthrough(request.form.get("passthrough"))
            if user_id is None:
                LOG.e("Paddle passthrough not signed by us. %s", request.form)
                return "Invalid passthrough", 400

            user = User.get(user_id)
            if not user:
                LOG.e("No such user %s for paddle callback %s", user_id, request.form)
                return "No such user", 400

            subscription_plan_id = int(request.form.get("subscription_plan_id"))

            if subscription_plan_id in PADDLE_MONTHLY_PRODUCT_IDS:
                plan = PlanEnum.monthly
            elif subscription_plan_id in PADDLE_YEARLY_PRODUCT_IDS:
                plan = PlanEnum.yearly
            else:
                LOG.e(
                    "Unknown subscription_plan_id %s %s",
                    subscription_plan_id,
                    request.form,
                )
                return "No such subscription", 400

            sub = Subscription.get_by(user_id=user.id)
            subscription_id = request.form.get("subscription_id")

            # defense in depth: a user with an active subscription cannot reach
            # the pricing page, so a checkout for a different subscription can
            # only be someone else's.
            if (
                sub
                and sub.subscription_id != subscription_id
                and not sub.cancelled
                and sub.is_active()
            ):
                LOG.e(
                    "Paddle callback would overwrite the active subscription %s of user %s. %s",
                    sub.subscription_id,
                    user,
                    request.form,
                )
                return "User already has an active subscription", 400

            if not sub:
                LOG.d(f"create a new Subscription for user {user}")
                Subscription.create(
                    user_id=user.id,
                    cancel_url=request.form.get("cancel_url"),
                    update_url=request.form.get("update_url"),
                    subscription_id=subscription_id,
                    event_time=arrow.now(),
                    next_bill_date=arrow.get(
                        request.form.get("next_bill_date"), "YYYY-MM-DD"
                    ).date(),
                    plan=plan,
                )
                emit_user_audit_log(
                    user=user,
                    action=UserAuditLogAction.Upgrade,
                    message="Upgraded through Paddle",
                )
            else:
                LOG.d(f"Update an existing Subscription for user {user}")
                sub.cancel_url = request.form.get("cancel_url")
                sub.update_url = request.form.get("update_url")
                sub.subscription_id = subscription_id
                sub.event_time = arrow.now()
                sub.next_bill_date = arrow.get(
                    request.form.get("next_bill_date"), "YYYY-MM-DD"
                ).date()
                sub.plan = plan

                # make sure to set the new plan as not-cancelled
                # in case user cancels a plan and subscribes a new plan
                sub.cancelled = False
                emit_user_audit_log(
                    user=user,
                    action=UserAuditLogAction.SubscriptionExtended,
                    message="Extended Paddle subscription",
                )

            execute_subscription_webhook(user)
            LOG.d("User %s upgrades!", user)

            Session.commit()

        elif request.form.get("alert_name") == "subscription_payment_succeeded":
            subscription_id = request.form.get("subscription_id")
            LOG.d("Update subscription %s", subscription_id)

            sub: Subscription = Subscription.get_by(subscription_id=subscription_id)
            # when user subscribes, the "subscription_payment_succeeded" can arrive BEFORE "subscription_created"
            # at that time, subscription object does not exist yet
            if sub:
                sub.event_time = arrow.now()
                sub.next_bill_date = arrow.get(
                    request.form.get("next_bill_date"), "YYYY-MM-DD"
                ).date()

                Session.commit()
                execute_subscription_webhook(sub.user)

        elif request.form.get("alert_name") == "subscription_cancelled":
            subscription_id = request.form.get("subscription_id")

            sub: Subscription = Subscription.get_by(subscription_id=subscription_id)
            if sub:
                # cancellation_effective_date should be the same as next_bill_date
                LOG.w(
                    "Cancel subscription %s %s on %s, next bill date %s",
                    subscription_id,
                    sub.user,
                    request.form.get("cancellation_effective_date"),
                    sub.next_bill_date,
                )
                sub.event_time = arrow.now()

                sub.cancelled = True
                emit_user_audit_log(
                    user=sub.user,
                    action=UserAuditLogAction.SubscriptionCancelled,
                    message="Cancelled Paddle subscription",
                )
                Session.commit()

                user = sub.user

                send_email(
                    user.email,
                    "SimpleLogin - your subscription is canceled",
                    render(
                        "transactional/subscription-cancel.txt",
                        user=user,
                        end_date=request.form.get("cancellation_effective_date"),
                    ),
                )
                execute_subscription_webhook(sub.user)

            else:
                # user might have deleted their account
                LOG.i(f"Cancel non-exist subscription {subscription_id}")
                return "OK"
        elif request.form.get("alert_name") == "subscription_updated":
            subscription_id = request.form.get("subscription_id")

            sub: Subscription = Subscription.get_by(subscription_id=subscription_id)
            if sub:
                next_bill_date = request.form.get("next_bill_date")
                if not next_bill_date:
                    paddle_callback.failed_payment(sub, subscription_id)
                    return "OK"

                LOG.d(
                    "Update subscription %s %s on %s, next bill date %s",
                    subscription_id,
                    sub.user,
                    request.form.get("cancellation_effective_date"),
                    sub.next_bill_date,
                )
                if (
                    int(request.form.get("subscription_plan_id"))
                    == PADDLE_MONTHLY_PRODUCT_ID
                ):
                    plan = PlanEnum.monthly
                else:
                    plan = PlanEnum.yearly

                sub.cancel_url = request.form.get("cancel_url")
                sub.update_url = request.form.get("update_url")
                sub.event_time = arrow.now()
                sub.next_bill_date = arrow.get(
                    request.form.get("next_bill_date"), "YYYY-MM-DD"
                ).date()
                sub.plan = plan

                # make sure to set the new plan as not-cancelled
                sub.cancelled = False
                emit_user_audit_log(
                    user=sub.user,
                    action=UserAuditLogAction.SubscriptionExtended,
                    message="Extended Paddle subscription",
                )

                Session.commit()
                execute_subscription_webhook(sub.user)
            else:
                LOG.w(
                    f"update non-exist subscription {subscription_id}. {request.form}"
                )
                return "No such subscription", 400
        elif request.form.get("alert_name") == "payment_refunded":
            subscription_id = request.form.get("subscription_id")
            LOG.d("Refund request for subscription %s", subscription_id)

            sub: Subscription = Subscription.get_by(subscription_id=subscription_id)

            if sub:
                user = sub.user
                Subscription.delete(sub.id)
                emit_user_audit_log(
                    user=user,
                    action=UserAuditLogAction.SubscriptionCancelled,
                    message="Paddle subscription cancelled as user requested a refund",
                )
                Session.commit()
                LOG.e("%s requests a refund", user)
                execute_subscription_webhook(sub.user)

        elif request.form.get("alert_name") == "subscription_payment_refunded":
            subscription_id = request.form.get("subscription_id")
            sub: Subscription = Subscription.get_by(subscription_id=subscription_id)
            LOG.d(
                "Handle subscription_payment_refunded for subscription %s",
                subscription_id,
            )

            if not sub:
                LOG.w(
                    "No such subscription for %s, payload %s",
                    subscription_id,
                    request.form,
                )
                return "No such subscription"

            plan_id = int(request.form["subscription_plan_id"])
            if request.form["refund_type"] == "full":
                if plan_id in PADDLE_MONTHLY_PRODUCT_IDS:
                    LOG.d("subtract 1 month from next_bill_date %s", sub.next_bill_date)
                    sub.next_bill_date = sub.next_bill_date - relativedelta(months=1)
                    LOG.d("next_bill_date is %s", sub.next_bill_date)
                    Session.commit()
                elif plan_id in PADDLE_YEARLY_PRODUCT_IDS:
                    LOG.d("subtract 1 year from next_bill_date %s", sub.next_bill_date)
                    sub.next_bill_date = sub.next_bill_date - relativedelta(years=1)
                    LOG.d("next_bill_date is %s", sub.next_bill_date)
                    Session.commit()
                else:
                    LOG.e("Unknown plan_id %s", plan_id)
            else:
                LOG.w("partial subscription_payment_refunded, not handled")
            execute_subscription_webhook(sub.user)

        return "OK"

    @app.route("/paddle_coupon", methods=["GET", "POST"])
    def paddle_coupon():
        LOG.d("paddle coupon callback %s", request.form)

        if not paddle_utils.verify_incoming_request(dict(request.form)):
            LOG.e("request not coming from paddle. Request data:%s", dict(request.form))
            return "KO", 400

        product_id = request.form.get("p_product_id")
        if product_id != PADDLE_COUPON_ID:
            LOG.e("product_id %s not match with %s", product_id, PADDLE_COUPON_ID)
            return "KO", 400

        email = request.form.get("email")
        LOG.d("Paddle coupon request for %s", email)

        coupon = Coupon.create(
            code=random_string(30),
            comment="For 1-year coupon",
            expires_date=arrow.now().shift(years=1, days=-1),
            commit=True,
        )

        return (
            f"Your 1-year coupon is <b>{coupon.code}</b> <br> "
            f"It's valid until <b>{coupon.expires_date.date().isoformat()}</b>"
        )

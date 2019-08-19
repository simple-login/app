import stripe
from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from stripe.error import CardError

from app.config import STRIPE_API, STRIPE_YEARLY_PLAN
from app.dashboard.base import dashboard_bp
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import PlanEnum


@dashboard_bp.route("/pricing", methods=["GET", "POST"])
@login_required
def pricing():
    # sanity check: make sure this page is only for free user that has never subscribed before
    # case user unsubscribe and re-subscribe will be handled later
    if current_user.is_premium():
        flash("You are already a premium user", "warning")
        return redirect(url_for("dashboard.index"))

    if (
        current_user.stripe_customer_id
        or current_user.stripe_card_token
        or current_user.stripe_subscription_id
    ):
        raise Exception("only user not exist on stripe can view this page")

    if stripe.Customer.list(email=current_user.email):
        raise Exception("user email is already used on stripe!")

    if request.method == "POST":
        plan_str = request.form.get("plan")  # yearly
        if plan_str == "yearly":
            plan = PlanEnum.yearly
        else:
            raise Exception("Plan must be either yearly or monthly")

        stripe_token = request.form.get("stripeToken")
        LOG.d("stripe card token %s for plan %s", stripe_token, plan)
        current_user.stripe_card_token = stripe_token

        try:
            customer = stripe.Customer.create(
                source=stripe_token,
                email=current_user.email,
                metadata={"id": current_user.id},
                name=current_user.name,
            )
        except CardError as e:
            LOG.exception("payment problem, code:%s", e.code)
            flash(
                "Payment refused with error {e.message}. Could you re-try with another card please?",
                "danger",
            )
        else:
            LOG.d("stripe customer %s", customer)
            current_user.stripe_customer_id = customer.id

            stripe_plan = STRIPE_YEARLY_PLAN
            subscription = stripe.Subscription.create(
                customer=current_user.stripe_customer_id,
                items=[{"plan": stripe_plan}],
                expand=["latest_invoice.payment_intent"],
            )

            LOG.d("stripe subscription %s", subscription)

            current_user.stripe_subscription_id = subscription.id

            db.session.commit()

            if subscription.latest_invoice.payment_intent.status == "succeeded":
                LOG.d("payment successful for user %s", current_user)
                current_user.plan = plan
                current_user.plan_expiration = None
                db.session.commit()
                flash("Thanks for your subscription!", "success")
                notify_admin(
                    f"user {current_user.email} has finished subscription",
                    f"plan: {plan}",
                )
                return redirect(url_for("dashboard.index"))

    return render_template("dashboard/pricing.html", stripe_api=STRIPE_API)

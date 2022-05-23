from flask import request, redirect, url_for, flash, render_template, g
from flask_login import login_user, current_user

from app import email_utils
from app.auth.base import auth_bp
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import ActivationCode
from app.utils import sanitize_next_url


@auth_bp.route("/activate", methods=["GET", "POST"])
@limiter.limit(
    "10/minute", deduct_when=lambda r: hasattr(g, "deduct_limit") and g.deduct_limit
)
def activate():
    if current_user.is_authenticated:
        return (
            render_template("auth/activate.html", error="You are already logged in"),
            400,
        )

    code = request.args.get("code")

    activation_code: ActivationCode = ActivationCode.get_by(code=code)

    if not activation_code:
        # Trigger rate limiter
        g.deduct_limit = True
        return (
            render_template(
                "auth/activate.html", error="Activation code cannot be found"
            ),
            400,
        )

    if activation_code.is_expired():
        return (
            render_template(
                "auth/activate.html",
                error="Activation code was expired",
                show_resend_activation=True,
            ),
            400,
        )

    user = activation_code.user
    user.activated = True
    login_user(user)

    # activation code is to be used only once
    ActivationCode.delete(activation_code.id)
    Session.commit()

    flash("Your account has been activated", "success")

    email_utils.send_welcome_email(user)

    # The activation link contains the original page, for ex authorize page
    if "next" in request.args:
        next_url = sanitize_next_url(request.args.get("next"))
        LOG.d("redirect user to %s", next_url)
        return redirect(next_url)
    else:
        LOG.d("redirect user to dashboard")
        return redirect(url_for("dashboard.index"))
        # todo: redirect to account_activated page when more features are added into the browser extension
        # return redirect(url_for("onboarding.account_activated"))

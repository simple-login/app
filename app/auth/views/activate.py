import arrow
from flask import request, redirect, url_for, flash, render_template
from flask_login import login_user, current_user

from app.auth.base import auth_bp
from app.extensions import db
from app.log import LOG
from app.models import ActivationCode


@auth_bp.route("/activate", methods=["GET", "POST"])
def activate():
    if current_user.is_authenticated:
        return (
            render_template("auth/activate.html", error="You are already logged in"),
            400,
        )

    code = request.args.get("code")

    activation_code: ActivationCode = ActivationCode.get_by(code=code)

    if not activation_code:
        return (
            render_template("auth/activate.html", error="Activation code not found"),
            400,
        )

    if activation_code.expired and activation_code.expired < arrow.now():
        return (
            render_template(
                "auth/activate.html",
                error="Activation code is expired",
                show_resend_activation=True,
            ),
            400,
        )

    user = activation_code.user
    user.activated = True
    login_user(user)

    # activation code is to be used only once
    activation_code.delete()
    db.session.commit()

    flash("Your account has been activated", "success")

    # The activation link contains the original page, for ex authorize page
    if "next" in request.args:
        next_url = request.args.get("next")
        LOG.debug("redirect user to %s", next_url)
        return redirect(next_url)
    else:
        LOG.debug("redirect user to dashboard")
        return redirect(url_for("dashboard.index"))

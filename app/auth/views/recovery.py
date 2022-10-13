import arrow
from flask import request, render_template, redirect, url_for, flash, session, g
from flask_login import login_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.config import MFA_USER_ID
from app.db import Session
from app.email_utils import send_invalid_totp_login_email
from app.extensions import limiter
from app.log import LOG
from app.models import User, RecoveryCode
from app.utils import sanitize_next_url


class RecoveryForm(FlaskForm):
    code = StringField("Code", validators=[validators.DataRequired()])


@auth_bp.route("/recovery", methods=["GET", "POST"])
@limiter.limit(
    "10/minute", deduct_when=lambda r: hasattr(g, "deduct_limit") and g.deduct_limit
)
def recovery_route():
    # passed from login page
    user_id = session.get(MFA_USER_ID)

    # user access this page directly without passing by login page
    if not user_id:
        flash("Unknown error, redirect back to main page", "warning")
        return redirect(url_for("auth.login"))

    user = User.get(user_id)

    if not user.two_factor_authentication_enabled():
        flash("Only user with MFA enabled should go to this page", "warning")
        return redirect(url_for("auth.login"))

    recovery_form = RecoveryForm()
    next_url = sanitize_next_url(request.args.get("next"))

    if recovery_form.validate_on_submit():
        code = recovery_form.code.data
        recovery_code = RecoveryCode.find_by_user_code(user, code)

        if recovery_code:
            if recovery_code.used:
                # Trigger rate limiter
                g.deduct_limit = True
                flash("Code already used", "error")
            else:
                del session[MFA_USER_ID]

                login_user(user)
                flash(f"Welcome back!", "success")

                recovery_code.used = True
                recovery_code.used_at = arrow.now()
                Session.commit()

                # User comes to login page from another page
                if next_url:
                    LOG.d("redirect user to %s", next_url)
                    return redirect(next_url)
                else:
                    LOG.d("redirect user to dashboard")
                    return redirect(url_for("dashboard.index"))
        else:
            # Trigger rate limiter
            g.deduct_limit = True
            flash("Incorrect code", "error")
            send_invalid_totp_login_email(user, "recovery")

    return render_template("auth/recovery.html", recovery_form=recovery_form)

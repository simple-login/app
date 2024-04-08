from functools import wraps
from time import time

from flask import render_template, flash, redirect, url_for, session, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, validators

from app.config import CONNECT_WITH_PROTON, OIDC_CLIENT_ID, CONNECT_WITH_OIDC_ICON
from app.dashboard.base import dashboard_bp
from app.extensions import limiter
from app.log import LOG
from app.models import PartnerUser, SocialAuth
from app.proton.utils import get_proton_partner
from app.utils import sanitize_next_url

_SUDO_GAP = 120


class LoginForm(FlaskForm):
    password = PasswordField("Password", validators=[validators.DataRequired()])


@dashboard_bp.route("/enter_sudo", methods=["GET", "POST"])
@limiter.limit("3/minute")
@login_required
def enter_sudo():
    password_check_form = LoginForm()

    if password_check_form.validate_on_submit():
        password = password_check_form.password.data

        if current_user.check_password(password):
            session["sudo_time"] = int(time())

            # User comes to sudo page from another page
            next_url = sanitize_next_url(request.args.get("next"))
            if next_url:
                LOG.d("redirect user to %s", next_url)
                return redirect(next_url)
            else:
                LOG.d("redirect user to dashboard")
                return redirect(url_for("dashboard.index"))
        else:
            flash("Incorrect password", "warning")

    proton_enabled = CONNECT_WITH_PROTON
    if proton_enabled:
        # Only for users that have the account linked
        partner_user = PartnerUser.get_by(user_id=current_user.id)
        if not partner_user or partner_user.partner_id != get_proton_partner().id:
            proton_enabled = False

    oidc_enabled = OIDC_CLIENT_ID is not None
    if oidc_enabled:
        oidc_enabled = (
            SocialAuth.get_by(user_id=current_user.id, social="oidc") is not None
        )

    return render_template(
        "dashboard/enter_sudo.html",
        password_check_form=password_check_form,
        next=request.args.get("next"),
        connect_with_proton=proton_enabled,
        connect_with_oidc=oidc_enabled,
        connect_with_oidc_icon=CONNECT_WITH_OIDC_ICON,
    )


def sudo_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if (
            "sudo_time" not in session
            or (time() - int(session["sudo_time"])) > _SUDO_GAP
        ):
            return redirect(url_for("dashboard.enter_sudo", next=request.path))
        return f(*args, **kwargs)

    return wrap

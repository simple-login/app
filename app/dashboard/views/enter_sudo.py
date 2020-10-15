from functools import wraps
from time import time

from flask import render_template, flash, redirect, url_for, session, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, validators

from app.dashboard.base import dashboard_bp
from app.log import LOG

_SUDO_GAP = 900


class LoginForm(FlaskForm):
    password = PasswordField("Password", validators=[validators.DataRequired()])


@dashboard_bp.route("/enter_sudo", methods=["GET", "POST"])
@login_required
def enter_sudo():
    password_check_form = LoginForm()

    if password_check_form.validate_on_submit():
        password = password_check_form.password.data

        if current_user.check_password(password):
            session["sudo_time"] = int(time())

            # User comes to sudo page from another page
            next_url = request.args.get("next")
            if next_url:
                LOG.debug("redirect user to %s", next_url)
                return redirect(next_url)
            else:
                LOG.debug("redirect user to dashboard")
                return redirect(url_for("dashboard.index"))
        else:
            flash("Incorrect password", "warning")

    return render_template(
        "dashboard/enter_sudo.html", password_check_form=password_check_form
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

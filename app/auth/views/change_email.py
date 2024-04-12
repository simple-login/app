from flask import request, flash, render_template, redirect, url_for
from flask_login import login_user

from app.auth.base import auth_bp
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import EmailChange, ResetPasswordCode


@auth_bp.route("/change_email", methods=["GET", "POST"])
@limiter.limit("3/hour")
def change_email():
    code = request.args.get("code")

    email_change: EmailChange = EmailChange.get_by(code=code)

    if not email_change:
        return render_template("auth/change_email.html")

    if email_change.is_expired():
        # delete the expired email
        EmailChange.delete(email_change.id)
        Session.commit()
        return render_template("auth/change_email.html")

    user = email_change.user
    old_email = user.email
    user.email = email_change.new_email

    EmailChange.delete(email_change.id)
    ResetPasswordCode.filter_by(user_id=user.id).delete()
    Session.commit()

    LOG.i(f"User {user} has changed their email from {old_email} to {user.email}")
    flash("Your new email has been updated", "success")

    login_user(user)

    return redirect(url_for("dashboard.index"))

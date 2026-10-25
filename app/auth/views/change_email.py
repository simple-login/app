from flask import request, flash, render_template, redirect, url_for

from app.auth.base import auth_bp
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import EmailChange, ResetPasswordCode, ApiKey, MfaBrowser
from app.user_settings import regenerate_user_alternative_id


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
    # Invalidate all API keys to log out from all sessions
    ApiKey.delete_all(user.id)
    # Revoke all trusted browser sessions
    MfaBrowser.filter_by(user_id=user.id).delete()
    # Change the alternative_id to log user out on other browsers
    regenerate_user_alternative_id(user, update_session=False)
    Session.commit()

    LOG.i(f"User {user} has changed their email from {old_email} to {user.email}")
    flash("Your new email has been updated", "success")

    # do not login_user here to require MFA if enabled
    # redirect to login page instead
    return redirect(url_for("auth.login"))

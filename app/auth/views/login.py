from flask import request, render_template, redirect, url_for, flash, g
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.auth.views.login_utils import after_login
from app.config import CONNECT_WITH_PROTON, CONNECT_WITH_OIDC_ICON, OIDC_CLIENT_ID
from app.events.auth_event import LoginEvent
from app.extensions import limiter
from app.log import LOG
from app.models import User
from app.pw_models import PasswordOracle
from app.utils import sanitize_email, sanitize_next_url, canonicalize_email


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])
    password = StringField("Password", validators=[validators.DataRequired()])


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    "10/minute", deduct_when=lambda r: hasattr(g, "deduct_limit") and g.deduct_limit
)
def login():
    next_url = sanitize_next_url(request.args.get("next"))

    if current_user.is_authenticated:
        if next_url:
            LOG.d("user is already authenticated, redirect to %s", next_url)
            return redirect(next_url)
        else:
            LOG.d("user is already authenticated, redirect to dashboard")
            return redirect(url_for("dashboard.index"))

    form = LoginForm(request.form)

    show_resend_activation = False

    if form.validate_on_submit():
        email = sanitize_email(form.email.data)
        canonical_email = canonicalize_email(email)
        user = User.get_by(email=email) or User.get_by(email=canonical_email)

        if not user or not user.check_password(form.password.data):
            if not user:
                # Do the hash to avoid timing attacks nevertheless
                dummy_pw = PasswordOracle()
                dummy_pw.password = (
                    "$2b$12$ZWqpL73h4rGNfLkJohAFAu0isqSw/bX9p/tzpbWRz/To5FAftaW8u"
                )
                dummy_pw.check_password(form.password.data)
            # Trigger rate limiter
            g.deduct_limit = True
            form.password.data = None
            flash("Email or password incorrect", "error")
            LoginEvent(LoginEvent.ActionType.failed).send()
        elif user.disabled:
            flash(
                "Your account is disabled. Please contact SimpleLogin team to re-enable your account.",
                "error",
            )
            LoginEvent(LoginEvent.ActionType.disabled_login).send()
        elif user.delete_on is not None:
            flash(
                f"Your account is scheduled to be deleted on {user.delete_on}",
                "error",
            )
            LoginEvent(LoginEvent.ActionType.scheduled_to_be_deleted).send()
        elif not user.activated:
            show_resend_activation = True
            flash(
                "Please check your inbox for the activation email. You can also have this email re-sent",
                "error",
            )
            LoginEvent(LoginEvent.ActionType.not_activated).send()
        else:
            LoginEvent(LoginEvent.ActionType.success).send()
            return after_login(user, next_url)

    return render_template(
        "auth/login.html",
        form=form,
        next_url=next_url,
        show_resend_activation=show_resend_activation,
        connect_with_proton=CONNECT_WITH_PROTON,
        connect_with_oidc=OIDC_CLIENT_ID is not None,
        connect_with_oidc_icon=CONNECT_WITH_OIDC_ICON,
    )

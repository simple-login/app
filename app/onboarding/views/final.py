from app.extensions import limiter
from app.models import Alias
from app.onboarding.base import onboarding_bp
from app.email_utils import send_test_email_alias
from flask import render_template, request, flash
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, validators


class SendEmailForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])


@onboarding_bp.route("/final", methods=["GET", "POST"])
@login_required
@limiter.limit("10/minute")
def final():
    form = SendEmailForm(request.form)
    if form.validate_on_submit():
        alias = Alias.get_by(email=form.email.data)
        if alias and alias.user_id == current_user.id:
            send_test_email_alias(alias.email, current_user.name)
            flash("An email is sent to your alias", "success")

    return render_template(
        "onboarding/final.html",
        form=form,
    )

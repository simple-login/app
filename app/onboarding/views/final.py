from app.extensions import limiter
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
        send_test_email_alias(form.email.data, current_user.name)
        flash("We have sent a test e-mail to your alias", "success")

    return render_template(
        "onboarding/final.html",
        form=form,
    )

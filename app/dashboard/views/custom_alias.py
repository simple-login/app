from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.config import EMAIL_DOMAIN, HIGHLIGHT_GEN_EMAIL_ID
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, DeletedAlias
from app.utils import convert_to_id, random_string


class CustomAliasForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])


@dashboard_bp.route("/custom_alias", methods=["GET", "POST"])
@login_required
def custom_alias():
    # check if user has the right to create custom alias
    if not current_user.can_create_custom_email():
        # notify admin
        LOG.error("user %s tries to create custom alias", current_user)
        flash("ony premium user can choose custom alias", "warning")
        return redirect(url_for("dashboard.index"))

    form = CustomAliasForm()
    error = ""

    if form.validate_on_submit():
        email = form.email.data
        email = convert_to_id(email)
        email_suffix = request.form.get("email-suffix")

        if len(email) < 3:
            error = "email must be at least 3 letters"
        else:
            full_email = f"{email}.{email_suffix}@{EMAIL_DOMAIN}"
            # check if email already exists
            if GenEmail.get_by(email=full_email) or DeletedAlias.get_by(
                email=full_email
            ):
                error = "email already chosen, please choose another one"
            else:
                # create the new alias
                LOG.d("create custom alias %s for user %s", full_email, current_user)
                gen_email = GenEmail.create(
                    email=full_email, user_id=current_user.id, custom=True
                )
                db.session.commit()

                flash(f"Email alias {full_email} has been created", "success")
                session[HIGHLIGHT_GEN_EMAIL_ID] = gen_email.id

                return redirect(url_for("dashboard.index"))

    email_suffix = random_string(6)
    return render_template(
        "dashboard/custom_alias.html",
        form=form,
        error=error,
        email_suffix=email_suffix,
        EMAIL_DOMAIN=EMAIL_DOMAIN,
    )

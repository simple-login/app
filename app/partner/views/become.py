from flask import request, render_template, redirect, url_for, flash
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField

from app.config import PARTNER_CODES
from app.email_utils import notify_admin
from app.extensions import db
from app.models import Partner
from app.partner.base import partner_bp


class BecomePartnerForm(FlaskForm):
    email = StringField("Email")
    name = StringField("Name")
    website = StringField("Website")
    additional_information = StringField("Additional Information")
    partner_code = StringField("Partner Code")


@partner_bp.route("/become", methods=["GET", "POST"])
def become():
    form = BecomePartnerForm(request.form)

    if form.validate_on_submit():
        # bypass the application
        if form.partner_code.data:
            if not current_user.is_authenticated:
                raise Exception("only authenticated user can enter partner code")

            if form.partner_code.data in PARTNER_CODES:
                notify_admin(
                    f"User {current_user.name} has become partner!",
                    {current_user.email},
                )

                current_user.is_developer = True
                db.session.commit()

                flash(
                    "Congratulations, you are now a SimpleLogin partner! "
                    "You will have access to tech resources on SimpleLogin.",
                    "success",
                )

                return redirect(url_for("developer.index"))
            else:
                error = (
                    "The partner code is unknown. Are you sure this is the right code?"
                )
                return render_template("partner/become.html", form=form, error=error)
        else:
            partner = Partner.create(
                email=form.email.data,
                name=form.name.data,
                website=form.website.data,
                additional_information=form.additional_information.data,
            )

            if current_user.is_authenticated:
                partner.user_id = current_user.id

            db.session.commit()

            notify_admin(
                f"New partner {partner.name} {partner.email} has signed up!",
                partner.website,
            )

            flash(
                "Your request has been submitted, we'll come back to you asap!",
                "success",
            )

        return redirect(url_for("partner.become"))

    return render_template("partner/become.html", form=form)

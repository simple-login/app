from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.config import EMAIL_SERVERS_WITH_PRIORITY, EMAIL_SERVERS
from app.dashboard.base import dashboard_bp
from app.dns_utils import get_mx_domains
from app.extensions import db
from app.models import CustomDomain


# todo: add more validation
class NewCustomDomainForm(FlaskForm):
    domain = StringField("domain", validators=[validators.DataRequired()])


@dashboard_bp.route("/custom_domain", methods=["GET", "POST"])
@login_required
def custom_domain():
    custom_domains = CustomDomain.query.filter_by(user_id=current_user.id).all()

    new_custom_domain_form = NewCustomDomainForm()

    errors = {}

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            custom_domain_id = request.form.get("custom-domain-id")
            custom_domain = CustomDomain.get(custom_domain_id)

            if not custom_domain:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.custom_domain"))
            elif custom_domain.user_id != current_user.id:
                flash("You cannot delete this domain", "warning")
                return redirect(url_for("dashboard.custom_domain"))

            name = custom_domain.domain
            CustomDomain.delete(custom_domain_id)
            db.session.commit()
            flash(f"Domain {name} has been deleted successfully", "success")

            return redirect(url_for("dashboard.custom_domain"))

        elif request.form.get("form-name") == "create":
            if new_custom_domain_form.validate():
                new_custom_domain = CustomDomain.create(
                    domain=new_custom_domain_form.domain.data, user_id=current_user.id
                )
                db.session.commit()

                flash(
                    f"New domain {new_custom_domain.domain} has been created successfully",
                    "success",
                )
                return redirect(url_for("dashboard.custom_domain"))
        elif request.form.get("form-name") == "check-domain":
            custom_domain_id = request.form.get("custom-domain-id")
            custom_domain = CustomDomain.get(custom_domain_id)

            if not custom_domain:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.custom_domain"))
            elif custom_domain.user_id != current_user.id:
                flash("You cannot delete this domain", "warning")
                return redirect(url_for("dashboard.custom_domain"))
            else:
                mx_domains = get_mx_domains(custom_domain.domain)
                if mx_domains != EMAIL_SERVERS:
                    errors[
                        custom_domain.id
                    ] = f"Your DNS is not correctly set. The MX record we obtain is {mx_domains}"
                else:
                    flash(
                        "Your domain is verified. Now it can be used to create custom alias",
                        "success",
                    )
                    custom_domain.verified = True
                    db.session.commit()

    return render_template(
        "dashboard/custom_domain.html",
        custom_domains=custom_domains,
        new_custom_domain_form=new_custom_domain_form,
        EMAIL_SERVERS_WITH_PRIORITY=EMAIL_SERVERS_WITH_PRIORITY,
        errors=errors,
    )

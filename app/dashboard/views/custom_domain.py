from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.config import EMAIL_SERVERS_WITH_PRIORITY
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.models import CustomDomain


# todo: add more validation
class NewCustomDomainForm(FlaskForm):
    domain = StringField("domain", validators=[validators.DataRequired()])


@dashboard_bp.route("/custom_domain", methods=["GET", "POST"])
@login_required
def custom_domain():
    # only premium user can add custom domain
    if not current_user.is_premium():
        flash("Only premium user can add custom domains", "warning")
        return redirect(url_for("dashboard.index"))

    custom_domains = CustomDomain.query.filter_by(user_id=current_user.id).all()

    new_custom_domain_form = NewCustomDomainForm()

    errors = {}

    if request.method == "POST":
        if request.form.get("form-name") == "create":
            if new_custom_domain_form.validate():
                new_custom_domain = CustomDomain.create(
                    domain=new_custom_domain_form.domain.data, user_id=current_user.id
                )
                db.session.commit()

                flash(f"New domain {new_custom_domain.domain} is created", "success")

                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns",
                        custom_domain_id=new_custom_domain.id,
                    )
                )

    return render_template(
        "dashboard/custom_domain.html",
        custom_domains=custom_domains,
        new_custom_domain_form=new_custom_domain_form,
        EMAIL_SERVERS_WITH_PRIORITY=EMAIL_SERVERS_WITH_PRIORITY,
        errors=errors,
    )

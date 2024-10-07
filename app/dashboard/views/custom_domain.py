from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import parallel_limiter
from app.config import EMAIL_SERVERS_WITH_PRIORITY
from app.custom_domain_utils import create_custom_domain
from app.dashboard.base import dashboard_bp
from app.models import CustomDomain


class NewCustomDomainForm(FlaskForm):
    domain = StringField(
        "domain", validators=[validators.DataRequired(), validators.Length(max=128)]
    )


@dashboard_bp.route("/custom_domain", methods=["GET", "POST"])
@login_required
@parallel_limiter.lock(only_when=lambda: request.method == "POST")
def custom_domain():
    custom_domains = CustomDomain.filter_by(
        user_id=current_user.id,
        is_sl_subdomain=False,
        pending_deletion=False,
    ).all()
    new_custom_domain_form = NewCustomDomainForm()

    if request.method == "POST":
        if request.form.get("form-name") == "create":
            if not current_user.is_premium():
                flash("Only premium plan can add custom domain", "warning")
                return redirect(url_for("dashboard.custom_domain"))

            if new_custom_domain_form.validate():
                res = create_custom_domain(
                    user=current_user, domain=new_custom_domain_form.domain.data
                )
                if res.success:
                    flash(f"New domain {res.instance.domain} is created", "success")
                    return redirect(
                        url_for(
                            "dashboard.domain_detail_dns",
                            custom_domain_id=res.instance.id,
                        )
                    )
                else:
                    flash(res.message, res.message_category)
                    if res.redirect:
                        return redirect(url_for(res.redirect))

    return render_template(
        "dashboard/custom_domain.html",
        custom_domains=custom_domains,
        new_custom_domain_form=new_custom_domain_form,
        EMAIL_SERVERS_WITH_PRIORITY=EMAIL_SERVERS_WITH_PRIORITY,
    )

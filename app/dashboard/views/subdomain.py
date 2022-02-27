import re

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.config import MAX_NB_SUBDOMAIN
from app.dashboard.base import dashboard_bp
from app.errors import SubdomainInTrashError
from app.log import LOG
from app.models import CustomDomain, Mailbox, SLDomain

# Only lowercase letters, numbers, dashes (-)  are currently supported
_SUBDOMAIN_PATTERN = r"[0-9a-z-]{1,}"


@dashboard_bp.route("/subdomain", methods=["GET", "POST"])
@login_required
def subdomain_route():
    if not current_user.subdomain_is_available():
        flash("Unknown error, redirect to the home page", "error")
        return redirect(url_for("dashboard.index"))

    sl_domains = SLDomain.filter_by(can_use_subdomain=True).all()
    subdomains = CustomDomain.filter_by(
        user_id=current_user.id, is_sl_subdomain=True
    ).all()

    errors = {}

    if request.method == "POST":
        if request.form.get("form-name") == "create":
            if not current_user.is_premium():
                flash("Only premium plan can add subdomain", "warning")
                return redirect(request.url)

            if current_user.subdomain_quota <= 0:
                flash(
                    f"You can't create more than {MAX_NB_SUBDOMAIN} subdomains", "error"
                )
                return redirect(request.url)

            subdomain = request.form.get("subdomain").lower().strip()
            domain = request.form.get("domain").lower().strip()

            if len(subdomain) < 3:
                flash("Subdomain must have at least 3 characters", "error")
                return redirect(request.url)

            if re.fullmatch(_SUBDOMAIN_PATTERN, subdomain) is None:
                flash(
                    "Subdomain can only contain lowercase letters, numbers and dashes (-)",
                    "error",
                )
                return redirect(request.url)

            if subdomain.endswith("-"):
                flash("Subdomain can't end with dash (-)", "error")
                return redirect(request.url)

            if domain not in [sl_domain.domain for sl_domain in sl_domains]:
                LOG.e("Domain %s is tampered by %s", domain, current_user)
                flash("Unknown error, refresh the page", "error")
                return redirect(request.url)

            full_domain = f"{subdomain}.{domain}"

            if CustomDomain.get_by(domain=full_domain):
                flash(f"{full_domain} already used", "error")
            elif Mailbox.filter(
                Mailbox.verified.is_(True),
                Mailbox.email.endswith(f"@{full_domain}"),
            ).first():
                flash(f"{full_domain} already used in a SimpleLogin mailbox", "error")
            else:
                try:
                    new_custom_domain = CustomDomain.create(
                        is_sl_subdomain=True,
                        catch_all=True,  # by default catch-all is enabled
                        domain=full_domain,
                        user_id=current_user.id,
                        verified=True,
                        dkim_verified=False,  # wildcard DNS does not work for DKIM
                        spf_verified=True,
                        dmarc_verified=False,  # wildcard DNS does not work for DMARC
                        ownership_verified=True,
                        commit=True,
                    )
                except SubdomainInTrashError:
                    flash(
                        f"{full_domain} has been used before and cannot be reused",
                        "error",
                    )
                else:
                    flash(
                        f"New subdomain {new_custom_domain.domain} is created",
                        "success",
                    )

                    return redirect(
                        url_for(
                            "dashboard.domain_detail",
                            custom_domain_id=new_custom_domain.id,
                        )
                    )

    return render_template(
        "dashboard/subdomain.html",
        sl_domains=sl_domains,
        errors=errors,
        subdomains=subdomains,
    )

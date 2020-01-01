from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user

from app.config import EMAIL_DOMAIN, HIGHLIGHT_GEN_EMAIL_ID
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, DeletedAlias, CustomDomain
from app.utils import convert_to_id, random_word, word_exist


@dashboard_bp.route("/custom_alias", methods=["GET", "POST"])
@login_required
def custom_alias():
    # check if user has the right to create custom alias
    if not current_user.can_create_new_alias():
        # notify admin
        LOG.error("user %s tries to create custom alias", current_user)
        flash("ony premium user can choose custom alias", "warning")
        return redirect(url_for("dashboard.index"))

    error = ""

    if request.method == "POST":
        if request.form.get("form-name") == "non-custom-domain-name":
            email_prefix = request.form.get("email-prefix")
            email_prefix = convert_to_id(email_prefix)
            email_suffix = request.form.get("email-suffix")

            # verify email_suffix
            if not word_exist(email_suffix):
                flash(
                    "nice try :). The suffix is there so no one can take all the *nice* aliases though",
                    "warning",
                )
                return redirect(url_for("dashboard.custom_alias"))

            if not email_prefix:
                error = "alias prefix cannot be empty"
            else:
                full_email = f"{email_prefix}.{email_suffix}@{EMAIL_DOMAIN}"
                # check if email already exists
                if GenEmail.get_by(email=full_email) or DeletedAlias.get_by(
                    email=full_email
                ):
                    error = "email already chosen, please choose another one"
                else:
                    # create the new alias
                    LOG.d(
                        "create custom alias %s for user %s", full_email, current_user
                    )
                    gen_email = GenEmail.create(
                        email=full_email, user_id=current_user.id
                    )
                    db.session.commit()

                    flash(f"Alias {full_email} has been created", "success")
                    session[HIGHLIGHT_GEN_EMAIL_ID] = gen_email.id

                    return redirect(url_for("dashboard.index"))
        elif request.form.get("form-name") == "custom-domain-name":
            custom_domain_id = request.form.get("custom-domain-id")
            email = request.form.get("email")

            custom_domain = CustomDomain.get(custom_domain_id)

            if not custom_domain:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.custom_alias"))
            elif custom_domain.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.custom_alias"))
            elif not custom_domain.verified:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.custom_alias"))

            full_email = f"{email}@{custom_domain.domain}"

            if GenEmail.get_by(email=full_email):
                error = f"{full_email} already exist, please choose another one"
            else:
                LOG.d(
                    "create custom alias %s for custom domain %s",
                    full_email,
                    custom_domain.domain,
                )
                gen_email = GenEmail.create(
                    email=full_email,
                    user_id=current_user.id,
                    custom_domain_id=custom_domain.id,
                )
                db.session.commit()
                flash(f"Alias {full_email} has been created", "success")

                session[HIGHLIGHT_GEN_EMAIL_ID] = gen_email.id
                return redirect(url_for("dashboard.index"))

    email_suffix = random_word()
    return render_template(
        "dashboard/custom_alias.html",
        error=error,
        email_suffix=email_suffix,
        EMAIL_DOMAIN=EMAIL_DOMAIN,
        custom_domains=current_user.verified_custom_domains(),
    )

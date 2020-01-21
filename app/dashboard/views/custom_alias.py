from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators, SelectField

from app.config import EMAIL_DOMAIN, HIGHLIGHT_GEN_EMAIL_ID, DISABLE_ALIAS_SUFFIX
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, DeletedAlias, CustomDomain
from app.utils import convert_to_id, random_word, word_exist


@dashboard_bp.route("/custom_alias", methods=["GET", "POST"])
@login_required
def custom_alias():
    # check if user has not exceeded the alias quota
    if not current_user.can_create_new_alias():
        # notify admin
        LOG.error("user %s tries to create custom alias", current_user)
        flash("ony premium user can choose custom alias", "warning")
        return redirect(url_for("dashboard.index"))

    user_custom_domains = [cd.domain for cd in current_user.verified_custom_domains()]
    suffixes = []

    # put custom domain first
    for alias_domain in user_custom_domains:
        suffixes.append("@" + alias_domain)

    # then default domain
    suffixes.append(
        ("" if DISABLE_ALIAS_SUFFIX else ".") + random_word() + "@" + EMAIL_DOMAIN
    )

    if request.method == "POST":
        alias_prefix = request.form.get("prefix")
        alias_suffix = request.form.get("suffix")

        if verify_prefix_suffix(
            current_user, alias_prefix, alias_suffix, user_custom_domains
        ):
            full_alias = alias_prefix + alias_suffix
            if GenEmail.get_by(email=full_alias):
                LOG.d("full alias already used %s", full_alias)
                flash(
                    f"Alias {full_alias} already exists, please choose another one",
                    "warning",
                )
            else:
                gen_email = GenEmail.create(user_id=current_user.id, email=full_alias)
                db.session.commit()
                flash(f"Alias {full_alias} has been created", "success")

                session[HIGHLIGHT_GEN_EMAIL_ID] = gen_email.id

                return redirect(url_for("dashboard.index"))
        # only happen if the request has been "hacked"
        else:
            flash("something went wrong", "warning")

    return render_template("dashboard/custom_alias.html", **locals())


def verify_prefix_suffix(user, alias_prefix, alias_suffix, user_custom_domains) -> bool:
    """verify if user could create an alias with the given prefix and suffix"""
    alias_prefix = alias_prefix.strip()
    alias_prefix = convert_to_id(alias_prefix)
    if not alias_prefix:  # should be caught on frontend
        return False

    # make sure alias_suffix is either .random_word@simplelogin.co or @my-domain.com
    alias_suffix = alias_suffix.strip()
    if alias_suffix.startswith("@"):
        alias_domain = alias_suffix[1:]
        # alias_domain can be either custom_domain or if DISABLE_ALIAS_SUFFIX, EMAIL_DOMAIN
        if DISABLE_ALIAS_SUFFIX:
            if alias_domain not in user_custom_domains and alias_domain != EMAIL_DOMAIN:
                LOG.error("wrong alias suffix %s, user %s", alias_suffix, user)
                return False
        else:
            if alias_domain not in user_custom_domains:
                LOG.error("wrong alias suffix %s, user %s", alias_suffix, user)
                return False
    else:
        if not alias_suffix.startswith("."):
            LOG.error("User %s submits a wrong alias suffix %s", user, alias_suffix)
            return False
        if not alias_suffix.endswith(EMAIL_DOMAIN):
            LOG.error(
                "Alias suffix should end with default alias domain %s",
                user,
                alias_suffix,
            )
            return False

        random_word_part = alias_suffix[1 : alias_suffix.find("@")]
        if not word_exist(random_word_part):
            LOG.error(
                "alias suffix %s needs to start with a random word, user %s",
                alias_suffix,
                user,
            )
            return False

    return True

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.config import DISABLE_ALIAS_SUFFIX, ALIAS_DOMAINS
from app.dashboard.base import dashboard_bp
from app.email_utils import email_belongs_to_alias_domains, get_email_domain_part
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, CustomDomain, DeletedAlias, Mailbox
from app.utils import convert_to_id, random_word, word_exist


@dashboard_bp.route("/custom_alias", methods=["GET", "POST"])
@login_required
def custom_alias():
    # check if user has not exceeded the alias quota
    if not current_user.can_create_new_alias():
        # notify admin
        LOG.error("user %s tries to create custom alias", current_user)
        flash(
            "You have reached free plan limit, please upgrade to create new aliases",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    user_custom_domains = [cd.domain for cd in current_user.verified_custom_domains()]
    # List of (is_custom_domain, alias-suffix)
    suffixes = []

    # put custom domain first
    for alias_domain in user_custom_domains:
        suffixes.append((True, "@" + alias_domain))

    # then default domain
    for domain in ALIAS_DOMAINS:
        suffixes.append(
            (
                False,
                ("" if DISABLE_ALIAS_SUFFIX else "." + random_word()) + "@" + domain,
            )
        )

    mailboxes = current_user.mailboxes()

    if request.method == "POST":
        alias_prefix = request.form.get("prefix")
        alias_suffix = request.form.get("suffix")
        mailbox_email = request.form.get("mailbox")
        alias_note = request.form.get("note")

        # check if mailbox is not tempered with
        if mailbox_email != current_user.email:
            mailbox = Mailbox.get_by(email=mailbox_email)
            if not mailbox or mailbox.user_id != current_user.id:
                flash("Something went wrong, please retry", "warning")
                return redirect(url_for("dashboard.custom_alias"))

        if verify_prefix_suffix(
            current_user, alias_prefix, alias_suffix, user_custom_domains
        ):
            full_alias = alias_prefix + alias_suffix

            if GenEmail.get_by(email=full_alias) or DeletedAlias.get_by(
                email=full_alias
            ):
                LOG.d("full alias already used %s", full_alias)
                flash(
                    f"Alias {full_alias} already exists, please choose another one",
                    "warning",
                )
            else:
                gen_email = GenEmail.create(
                    user_id=current_user.id, email=full_alias, note=alias_note
                )

                # get the custom_domain_id if alias is created with a custom domain
                alias_domain = get_email_domain_part(full_alias)
                custom_domain = CustomDomain.get_by(domain=alias_domain)
                if custom_domain:
                    LOG.d("Set alias %s domain to %s", full_alias, custom_domain)
                    gen_email.custom_domain_id = custom_domain.id

                # assign alias to a mailbox
                mailbox = Mailbox.get_by(email=mailbox_email)
                gen_email.mailbox_id = mailbox.id
                LOG.d("Set alias %s mailbox to %s", full_alias, mailbox)

                db.session.commit()
                flash(f"Alias {full_alias} has been created", "success")

                return redirect(
                    url_for("dashboard.index", highlight_gen_email_id=gen_email.id)
                )
        # only happen if the request has been "hacked"
        else:
            flash("something went wrong", "warning")

    return render_template("dashboard/custom_alias.html", **locals())


def verify_prefix_suffix(user, alias_prefix, alias_suffix, user_custom_domains) -> bool:
    """verify if user could create an alias with the given prefix and suffix"""
    if not alias_prefix or not alias_suffix:  # should be caught on frontend
        return False

    alias_prefix = alias_prefix.strip()
    alias_prefix = convert_to_id(alias_prefix)

    # make sure alias_suffix is either .random_word@simplelogin.co or @my-domain.com
    alias_suffix = alias_suffix.strip()
    if alias_suffix.startswith("@"):
        alias_domain = alias_suffix[1:]
        # alias_domain can be either custom_domain or if DISABLE_ALIAS_SUFFIX, one of the default ALIAS_DOMAINS
        if DISABLE_ALIAS_SUFFIX:
            if (
                alias_domain not in user_custom_domains
                and alias_domain not in ALIAS_DOMAINS
            ):
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

        full_alias = alias_prefix + alias_suffix
        if not email_belongs_to_alias_domains(full_alias):
            LOG.error(
                "Alias suffix should end with one of the alias domains %s",
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

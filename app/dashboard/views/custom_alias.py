from email_validator import validate_email, EmailNotValidError
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from itsdangerous import TimestampSigner, SignatureExpired
from sqlalchemy.exc import IntegrityError

from app.alias_suffix import get_alias_suffixes
from app.alias_utils import check_alias_prefix
from app.config import (
    DISABLE_ALIAS_SUFFIX,
    CUSTOM_ALIAS_SECRET,
    ALIAS_LIMIT,
)
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import (
    Alias,
    DeletedAlias,
    Mailbox,
    User,
    AliasMailbox,
    DomainDeletedAlias,
)

signer = TimestampSigner(CUSTOM_ALIAS_SECRET)


@dashboard_bp.route("/custom_alias", methods=["GET", "POST"])
@limiter.limit(ALIAS_LIMIT, methods=["POST"])
@login_required
def custom_alias():
    # check if user has not exceeded the alias quota
    if not current_user.can_create_new_alias():
        LOG.d("%s can't create new alias", current_user)
        flash(
            "You have reached free plan limit, please upgrade to create new aliases",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    user_custom_domains = [cd.domain for cd in current_user.verified_custom_domains()]
    alias_suffixes = get_alias_suffixes(current_user)
    at_least_a_premium_domain = False
    for alias_suffix in alias_suffixes:
        if not alias_suffix.is_custom and alias_suffix.is_premium:
            at_least_a_premium_domain = True
            break

    mailboxes = current_user.mailboxes()

    if request.method == "POST":
        alias_prefix = request.form.get("prefix").strip().lower().replace(" ", "")
        signed_alias_suffix = request.form.get("signed-alias-suffix")
        mailbox_ids = request.form.getlist("mailboxes")
        alias_note = request.form.get("note")

        if not check_alias_prefix(alias_prefix):
            flash(
                "Only lowercase letters, numbers, dashes (-), dots (.) and underscores (_) "
                "are currently supported for alias prefix. Cannot be more than 40 letters",
                "error",
            )
            return redirect(request.url)

        # check if mailbox is not tempered with
        mailboxes = []
        for mailbox_id in mailbox_ids:
            mailbox = Mailbox.get(mailbox_id)
            if (
                not mailbox
                or mailbox.user_id != current_user.id
                or not mailbox.verified
            ):
                flash("Something went wrong, please retry", "warning")
                return redirect(request.url)
            mailboxes.append(mailbox)

        if not mailboxes:
            flash("At least one mailbox must be selected", "error")
            return redirect(request.url)

        # hypothesis: user will click on the button in the 600 secs
        try:
            suffix = signer.unsign(signed_alias_suffix, max_age=600).decode()
        except SignatureExpired:
            LOG.w("Alias creation time expired for %s", current_user)
            flash("Alias creation time is expired, please retry", "warning")
            return redirect(request.url)
        except Exception:
            LOG.w("Alias suffix is tampered, user %s", current_user)
            flash("Unknown error, refresh the page", "error")
            return redirect(request.url)

        if verify_prefix_suffix(current_user, alias_prefix, suffix):
            full_alias = alias_prefix + suffix

            if ".." in full_alias:
                flash("Your alias can't contain 2 consecutive dots (..)", "error")
                return redirect(request.url)

            try:
                validate_email(
                    full_alias, check_deliverability=False, allow_smtputf8=False
                )
            except EmailNotValidError as e:
                flash(str(e), "error")
                return redirect(request.url)

            general_error_msg = f"{full_alias} cannot be used"

            if Alias.get_by(email=full_alias):
                alias = Alias.get_by(email=full_alias)
                if alias.user_id == current_user.id:
                    flash(f"You already have this alias {full_alias}", "error")
                else:
                    flash(general_error_msg, "error")
            elif DomainDeletedAlias.get_by(email=full_alias):
                domain_deleted_alias: DomainDeletedAlias = DomainDeletedAlias.get_by(
                    email=full_alias
                )
                custom_domain = domain_deleted_alias.domain
                if domain_deleted_alias.user_id == current_user.id:
                    flash(
                        f"You have deleted this alias before. You can restore it on "
                        f"{custom_domain.domain} 'Deleted Alias' page",
                        "error",
                    )
                else:
                    # should never happen as user can only choose their domains
                    LOG.e(
                        "Deleted Alias %s does not belong to user %s",
                        domain_deleted_alias,
                    )

            elif DeletedAlias.get_by(email=full_alias):
                flash(general_error_msg, "error")

            else:
                try:
                    alias = Alias.create(
                        user_id=current_user.id,
                        email=full_alias,
                        note=alias_note,
                        mailbox_id=mailboxes[0].id,
                    )
                    Session.flush()
                except IntegrityError:
                    LOG.w("Alias %s already exists", full_alias)
                    Session.rollback()
                    flash("Unknown error, please retry", "error")
                    return redirect(url_for("dashboard.custom_alias"))

                for i in range(1, len(mailboxes)):
                    AliasMailbox.create(
                        alias_id=alias.id,
                        mailbox_id=mailboxes[i].id,
                    )

                Session.commit()
                flash(f"Alias {full_alias} has been created", "success")

                return redirect(url_for("dashboard.index", highlight_alias_id=alias.id))
        # only happen if the request has been "hacked"
        else:
            flash("something went wrong", "warning")

    return render_template(
        "dashboard/custom_alias.html",
        user_custom_domains=user_custom_domains,
        alias_suffixes=alias_suffixes,
        at_least_a_premium_domain=at_least_a_premium_domain,
        mailboxes=mailboxes,
    )


def verify_prefix_suffix(user: User, alias_prefix, alias_suffix) -> bool:
    """verify if user could create an alias with the given prefix and suffix"""
    if not alias_prefix or not alias_suffix:  # should be caught on frontend
        return False

    user_custom_domains = [cd.domain for cd in user.verified_custom_domains()]

    # make sure alias_suffix is either .random_word@simplelogin.co or @my-domain.com
    alias_suffix = alias_suffix.strip()
    # alias_domain_prefix is either a .random_word or ""
    alias_domain_prefix, alias_domain = alias_suffix.split("@", 1)

    # alias_domain must be either one of user custom domains or built-in domains
    if alias_domain not in user.available_alias_domains():
        LOG.e("wrong alias suffix %s, user %s", alias_suffix, user)
        return False

    # SimpleLogin domain case:
    # 1) alias_suffix must start with "." and
    # 2) alias_domain_prefix must come from the word list
    if (
        alias_domain in user.available_sl_domains()
        and alias_domain not in user_custom_domains
        # when DISABLE_ALIAS_SUFFIX is true, alias_domain_prefix is empty
        and not DISABLE_ALIAS_SUFFIX
    ):

        if not alias_domain_prefix.startswith("."):
            LOG.e("User %s submits a wrong alias suffix %s", user, alias_suffix)
            return False

    else:
        if alias_domain not in user_custom_domains:
            if not DISABLE_ALIAS_SUFFIX:
                LOG.e("wrong alias suffix %s, user %s", alias_suffix, user)
                return False

            if alias_domain not in user.available_sl_domains():
                LOG.e("wrong alias suffix %s, user %s", alias_suffix, user)
                return False

    return True

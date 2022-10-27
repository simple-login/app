from email_validator import validate_email, EmailNotValidError
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from app import parallel_limiter
from app.alias_suffix import (
    get_alias_suffixes,
    check_suffix_signature,
    verify_prefix_suffix,
)
from app.alias_utils import check_alias_prefix
from app.config import (
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
    AliasMailbox,
    DomainDeletedAlias,
)


@dashboard_bp.route("/custom_alias", methods=["GET", "POST"])
@limiter.limit(ALIAS_LIMIT, methods=["POST"])
@login_required
@parallel_limiter.lock(name="alias_creation")
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

        try:
            suffix = check_suffix_signature(signed_alias_suffix)
            if not suffix:
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

from dataclasses import dataclass

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from itsdangerous import TimestampSigner, SignatureExpired
from sqlalchemy.exc import IntegrityError

from app.alias_utils import check_alias_prefix
from app.config import (
    DISABLE_ALIAS_SUFFIX,
    CUSTOM_ALIAS_SECRET,
)
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import (
    Alias,
    CustomDomain,
    DeletedAlias,
    Mailbox,
    User,
    AliasMailbox,
    DomainDeletedAlias,
)
from app.utils import convert_to_id, random_word, word_exist

signer = TimestampSigner(CUSTOM_ALIAS_SECRET)


def available_suffixes(user: User) -> [bool, str, str]:
    """Return (is_custom_domain, alias-suffix, time-signed alias-suffix)"""
    user_custom_domains = user.verified_custom_domains()

    # List of (is_custom_domain, alias-suffix, time-signed alias-suffix)
    suffixes = []

    # put custom domain first
    # for each user domain, generate both the domain and a random suffix version
    for alias_domain in user_custom_domains:
        suffix = "@" + alias_domain.domain
        suffixes.append((True, suffix, signer.sign(suffix).decode()))
        if alias_domain.random_prefix_generation:
            suffix = "." + random_word() + "@" + alias_domain.domain
            suffixes.append((True, suffix, signer.sign(suffix).decode()))

    # then SimpleLogin domain
    for domain in user.available_sl_domains():
        suffix = ("" if DISABLE_ALIAS_SUFFIX else "." + random_word()) + "@" + domain
        suffixes.append((False, suffix, signer.sign(suffix).decode()))

    return suffixes


@dataclass
class SuffixInfo:
    is_custom: bool
    suffix: str
    signed_suffix: str
    is_premium: bool


def available_suffixes_more_info(user: User) -> [SuffixInfo]:
    """
    Similar to as available_suffixes() but also return whether the suffix comes from a premium domain
    Note that is-premium-domain is only relevant for SL domain
    """
    user_custom_domains = user.verified_custom_domains()

    suffixes: [SuffixInfo] = []

    # put custom domain first
    # for each user domain, generate both the domain and a random suffix version
    for alias_domain in user_custom_domains:
        suffix = "@" + alias_domain.domain
        suffixes.append(SuffixInfo(True, suffix, signer.sign(suffix).decode(), False))
        if alias_domain.random_prefix_generation:
            suffix = "." + random_word() + "@" + alias_domain.domain
            suffixes.append(
                SuffixInfo(True, suffix, signer.sign(suffix).decode(), False)
            )

    # then SimpleLogin domain
    for sl_domain in user.get_sl_domains():
        suffix = (
            ("" if DISABLE_ALIAS_SUFFIX else "." + random_word())
            + "@"
            + sl_domain.domain
        )
        suffixes.append(
            SuffixInfo(
                False, suffix, signer.sign(suffix).decode(), sl_domain.premium_only
            )
        )

    return suffixes


@dashboard_bp.route("/custom_alias", methods=["GET", "POST"])
@login_required
def custom_alias():
    # check if user has not exceeded the alias quota
    if not current_user.can_create_new_alias():
        LOG.warning("user %s tries to create custom alias", current_user)
        flash(
            "You have reached free plan limit, please upgrade to create new aliases",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    user_custom_domains = [cd.domain for cd in current_user.verified_custom_domains()]
    suffixes = available_suffixes_more_info(current_user)
    at_least_a_premium_domain = False
    for suffix in suffixes:
        if not suffix.is_custom and suffix.is_premium:
            at_least_a_premium_domain = True
            break

    mailboxes = current_user.mailboxes()

    if request.method == "POST":
        alias_prefix = request.form.get("prefix").strip().lower().replace(" ", "")
        signed_suffix = request.form.get("suffix")
        mailbox_ids = request.form.getlist("mailboxes")
        alias_note = request.form.get("note")

        if not check_alias_prefix(alias_prefix):
            flash(
                "Only lowercase letters, numbers, dashes (-) and underscores (_) "
                "are currently supported for alias prefix",
                "error",
            )
            return redirect(url_for("dashboard.custom_alias"))

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
                return redirect(url_for("dashboard.custom_alias"))
            mailboxes.append(mailbox)

        if not mailboxes:
            flash("At least one mailbox must be selected", "error")
            return redirect(url_for("dashboard.custom_alias"))

        # hypothesis: user will click on the button in the 600 secs
        try:
            alias_suffix = signer.unsign(signed_suffix, max_age=600).decode()
        except SignatureExpired:
            LOG.warning("Alias creation time expired for %s", current_user)
            flash("Alias creation time is expired, please retry", "warning")
            return redirect(url_for("dashboard.custom_alias"))
        except Exception:
            LOG.warning("Alias suffix is tampered, user %s", current_user)
            flash("Unknown error, refresh the page", "error")
            return redirect(url_for("dashboard.custom_alias"))

        if verify_prefix_suffix(current_user, alias_prefix, alias_suffix):
            full_alias = alias_prefix + alias_suffix

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
                    LOG.exception(
                        "Deleted Alias %s does not belong to user %s",
                        domain_deleted_alias,
                    )

            elif DeletedAlias.get_by(email=full_alias):
                flash(general_error_msg, "error")

            else:
                custom_domain_id = None
                # get the custom_domain_id if alias is created with a custom domain
                if alias_suffix.startswith("@"):
                    alias_domain = alias_suffix[1:]
                    domain = CustomDomain.get_by(domain=alias_domain)

                    # check if the alias is currently in the domain trash
                    if domain and DomainDeletedAlias.get_by(
                        domain_id=domain.id, email=full_alias
                    ):
                        flash(
                            f"Alias {full_alias} is currently in the {domain.domain} trash. "
                            f"Please remove it from the trash in order to re-create it.",
                            "warning",
                        )
                        return redirect(url_for("dashboard.custom_alias"))

                    if domain:
                        custom_domain_id = domain.id

                try:
                    alias = Alias.create(
                        user_id=current_user.id,
                        email=full_alias,
                        note=alias_note,
                        mailbox_id=mailboxes[0].id,
                        custom_domain_id=custom_domain_id,
                    )
                    db.session.flush()
                except IntegrityError:
                    LOG.warning("Alias %s already exists", full_alias)
                    db.session.rollback()
                    flash("Unknown error, please retry", "error")
                    return redirect(url_for("dashboard.custom_alias"))

                for i in range(1, len(mailboxes)):
                    AliasMailbox.create(
                        alias_id=alias.id,
                        mailbox_id=mailboxes[i].id,
                    )

                db.session.commit()
                flash(f"Alias {full_alias} has been created", "success")

                return redirect(url_for("dashboard.index", highlight_alias_id=alias.id))
        # only happen if the request has been "hacked"
        else:
            flash("something went wrong", "warning")

    return render_template(
        "dashboard/custom_alias.html",
        user_custom_domains=user_custom_domains,
        suffixes=suffixes,
        at_least_a_premium_domain=at_least_a_premium_domain,
        mailboxes=mailboxes,
    )


def verify_prefix_suffix(user: User, alias_prefix, alias_suffix) -> bool:
    """verify if user could create an alias with the given prefix and suffix"""
    if not alias_prefix or not alias_suffix:  # should be caught on frontend
        return False

    user_custom_domains = [cd.domain for cd in user.verified_custom_domains()]
    alias_prefix = alias_prefix.strip()
    alias_prefix = convert_to_id(alias_prefix)

    # make sure alias_suffix is either .random_word@simplelogin.co or @my-domain.com
    alias_suffix = alias_suffix.strip()
    # alias_domain_prefix is either a .random_word or ""
    alias_domain_prefix, alias_domain = alias_suffix.split("@", 1)

    # alias_domain must be either one of user custom domains or built-in domains
    if alias_domain not in user.available_alias_domains():
        LOG.exception("wrong alias suffix %s, user %s", alias_suffix, user)
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
            LOG.exception("User %s submits a wrong alias suffix %s", user, alias_suffix)
            return False

        random_word_part = alias_domain_prefix[1:]
        if not word_exist(random_word_part):
            LOG.exception(
                "alias suffix %s needs to start with a random word, user %s",
                alias_suffix,
                user,
            )
            return False
    else:
        if alias_domain not in user_custom_domains:
            if not DISABLE_ALIAS_SUFFIX:
                LOG.exception("wrong alias suffix %s, user %s", alias_suffix, user)
                return False

            if alias_domain not in user.available_sl_domains():
                LOG.exception("wrong alias suffix %s, user %s", alias_suffix, user)
                return False

    return True

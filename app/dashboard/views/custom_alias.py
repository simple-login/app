import json
from dataclasses import dataclass, asdict

from email_validator import validate_email, EmailNotValidError
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from itsdangerous import TimestampSigner, SignatureExpired
from sqlalchemy.exc import IntegrityError

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
    CustomDomain,
    DeletedAlias,
    Mailbox,
    User,
    AliasMailbox,
    DomainDeletedAlias,
)

signer = TimestampSigner(CUSTOM_ALIAS_SECRET)


@dataclass
class SuffixInfo:
    """
    Alias suffix info
    WARNING: should use AliasSuffix instead
    """

    # whether this is a custom domain
    is_custom: bool
    suffix: str
    signed_suffix: str

    # whether this is a premium SL domain. Not apply to custom domain
    is_premium: bool


def get_available_suffixes(user: User) -> [SuffixInfo]:
    """
    WARNING: should use get_alias_suffixes() instead
    """
    user_custom_domains = user.verified_custom_domains()

    suffixes: [SuffixInfo] = []

    # put custom domain first
    # for each user domain, generate both the domain and a random suffix version
    for custom_domain in user_custom_domains:
        if custom_domain.random_prefix_generation:
            suffix = "." + user.get_random_alias_suffix() + "@" + custom_domain.domain
            suffix_info = SuffixInfo(True, suffix, signer.sign(suffix).decode(), False)
            if user.default_alias_custom_domain_id == custom_domain.id:
                suffixes.insert(0, suffix_info)
            else:
                suffixes.append(suffix_info)

        suffix = "@" + custom_domain.domain
        suffix_info = SuffixInfo(True, suffix, signer.sign(suffix).decode(), False)

        # put the default domain to top
        # only if random_prefix_generation isn't enabled
        if (
            user.default_alias_custom_domain_id == custom_domain.id
            and not custom_domain.random_prefix_generation
        ):
            suffixes.insert(0, suffix_info)
        else:
            suffixes.append(suffix_info)

    # then SimpleLogin domain
    for sl_domain in user.get_sl_domains():
        suffix = (
            ("" if DISABLE_ALIAS_SUFFIX else "." + user.get_random_alias_suffix())
            + "@"
            + sl_domain.domain
        )
        suffix_info = SuffixInfo(
            False, suffix, signer.sign(suffix).decode(), sl_domain.premium_only
        )
        # put the default domain to top
        if user.default_alias_public_domain_id == sl_domain.id:
            suffixes.insert(0, suffix_info)
        else:
            suffixes.append(suffix_info)

    return suffixes


@dataclass
class AliasSuffix:
    # whether this is a custom domain
    is_custom: bool
    suffix: str

    # whether this is a premium SL domain. Not apply to custom domain
    is_premium: bool

    # can be either Custom or SL domain
    domain: str

    # if custom domain, whether the custom domain has MX verified, i.e. can receive emails
    mx_verified: bool = True

    def serialize(self):
        return json.dumps(asdict(self))

    @classmethod
    def deserialize(cls, data: str) -> "AliasSuffix":
        return AliasSuffix(**json.loads(data))


def get_alias_suffixes(user: User) -> [AliasSuffix]:
    """
    Similar to as get_available_suffixes() but also return custom domain that doesn't have MX set up.
    """
    user_custom_domains = CustomDomain.filter_by(
        user_id=user.id, ownership_verified=True
    ).all()

    alias_suffixes: [AliasSuffix] = []

    # put custom domain first
    # for each user domain, generate both the domain and a random suffix version
    for custom_domain in user_custom_domains:
        if custom_domain.random_prefix_generation:
            suffix = "." + user.get_random_alias_suffix() + "@" + custom_domain.domain
            alias_suffix = AliasSuffix(
                is_custom=True,
                suffix=suffix,
                is_premium=False,
                domain=custom_domain.domain,
                mx_verified=custom_domain.verified,
            )
            if user.default_alias_custom_domain_id == custom_domain.id:
                alias_suffixes.insert(0, alias_suffix)
            else:
                alias_suffixes.append(alias_suffix)

        suffix = "@" + custom_domain.domain
        alias_suffix = AliasSuffix(
            is_custom=True,
            suffix=suffix,
            is_premium=False,
            domain=custom_domain.domain,
            mx_verified=custom_domain.verified,
        )

        # put the default domain to top
        # only if random_prefix_generation isn't enabled
        if (
            user.default_alias_custom_domain_id == custom_domain.id
            and not custom_domain.random_prefix_generation
        ):
            alias_suffixes.insert(0, alias_suffix)
        else:
            alias_suffixes.append(alias_suffix)

    # then SimpleLogin domain
    for sl_domain in user.get_sl_domains():
        suffix = (
            ("" if DISABLE_ALIAS_SUFFIX else "." + user.get_random_alias_suffix())
            + "@"
            + sl_domain.domain
        )
        alias_suffix = AliasSuffix(
            is_custom=False,
            suffix=suffix,
            is_premium=sl_domain.premium_only,
            domain=sl_domain.domain,
            mx_verified=True,
        )

        # put the default domain to top
        if user.default_alias_public_domain_id == sl_domain.id:
            alias_suffixes.insert(0, alias_suffix)
        else:
            alias_suffixes.append(alias_suffix)

    return alias_suffixes


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

    alias_suffixes_with_signature = [
        (alias_suffix, signer.sign(alias_suffix.serialize()).decode())
        for alias_suffix in alias_suffixes
    ]

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
            signed_alias_suffix_decoded = signer.unsign(
                signed_alias_suffix, max_age=600
            ).decode()
            alias_suffix: AliasSuffix = AliasSuffix.deserialize(
                signed_alias_suffix_decoded
            )
        except SignatureExpired:
            LOG.w("Alias creation time expired for %s", current_user)
            flash("Alias creation time is expired, please retry", "warning")
            return redirect(request.url)
        except Exception:
            LOG.w("Alias suffix is tampered, user %s", current_user)
            flash("Unknown error, refresh the page", "error")
            return redirect(request.url)

        if verify_prefix_suffix(current_user, alias_prefix, alias_suffix.suffix):
            full_alias = alias_prefix + alias_suffix.suffix

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
        alias_suffixes_with_signature=alias_suffixes_with_signature,
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

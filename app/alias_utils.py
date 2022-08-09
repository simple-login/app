import re
from typing import Optional, Tuple

from email_validator import validate_email, EmailNotValidError
from sqlalchemy.exc import IntegrityError, DataError

from app.config import (
    BOUNCE_PREFIX_FOR_REPLY_PHASE,
    BOUNCE_PREFIX,
    BOUNCE_SUFFIX,
    VERP_PREFIX,
)
from app.db import Session
from app.email_utils import (
    get_email_domain_part,
    send_cannot_create_directory_alias,
    can_create_directory_for_address,
    send_cannot_create_directory_alias_disabled,
    get_email_local_part,
    send_cannot_create_domain_alias,
)
from app.errors import AliasInTrashError
from app.log import LOG
from app.models import (
    Alias,
    CustomDomain,
    Directory,
    User,
    DeletedAlias,
    DomainDeletedAlias,
    AliasMailbox,
    Mailbox,
    EmailLog,
    Contact,
    AutoCreateRule,
)
from app.regex_utils import regex_match


def get_user_if_alias_would_auto_create(
    address: str, notify_user: bool = False
) -> Optional[User]:
    banned_prefix = f"{VERP_PREFIX}."
    if address.startswith(banned_prefix):
        LOG.w("alias %s can't start with %s", address, banned_prefix)
        return None

    try:
        # Prevent addresses with unicode characters (🤯) in them for now.
        validate_email(address, check_deliverability=False, allow_smtputf8=False)
    except EmailNotValidError:
        return None

    domain_and_rule = check_if_alias_can_be_auto_created_for_custom_domain(
        address, notify_user=notify_user
    )
    if domain_and_rule:
        return domain_and_rule[0].user
    directory = check_if_alias_can_be_auto_created_for_a_directory(
        address, notify_user=notify_user
    )
    if directory:
        return directory.user

    return None


def check_if_alias_can_be_auto_created_for_custom_domain(
    address: str, notify_user: bool = True
) -> Optional[Tuple[CustomDomain, Optional[AutoCreateRule]]]:
    """
    Check if this address would generate an auto created alias.
    If that's the case return the domain that would create it and the rule that triggered it.
    If there's no rule it's a catchall creation
    """
    alias_domain = get_email_domain_part(address)
    custom_domain: CustomDomain = CustomDomain.get_by(domain=alias_domain)

    if not custom_domain:
        return None

    user: User = custom_domain.user
    if user.disabled:
        LOG.i("Disabled user %s can't create new alias via custom domain", user)
        return None

    if not user.can_create_new_alias():
        LOG.d(f"{user} can't create new custom-domain alias {address}")
        if notify_user:
            send_cannot_create_domain_alias(custom_domain.user, address, alias_domain)
        return None

    if not custom_domain.catch_all:
        if len(custom_domain.auto_create_rules) == 0:
            return None
        local = get_email_local_part(address)

        for rule in custom_domain.auto_create_rules:
            if regex_match(rule.regex, local):
                LOG.d(
                    "%s passes %s on %s",
                    address,
                    rule.regex,
                    custom_domain,
                )
                return custom_domain, rule
        else:  # no rule passes
            LOG.d("no rule passed to create %s", local)
            return None
    LOG.d("Create alias via catchall")

    return custom_domain, None


def check_if_alias_can_be_auto_created_for_a_directory(
    address: str, notify_user: bool = True
) -> Optional[Directory]:
    """
    Try to create an alias with directory
    If an alias would be created, return the dictionary that would trigger the creation. Otherwise, return None.
    """
    # check if alias belongs to a directory, ie having directory/anything@EMAIL_DOMAIN format
    if not can_create_directory_for_address(address):
        return None

    # alias contains one of the 3 special directory separator: "/", "+" or "#"
    if "/" in address:
        sep = "/"
    elif "+" in address:
        sep = "+"
    elif "#" in address:
        sep = "#"
    else:
        # if there's no directory separator in the alias, no way to auto-create it
        return None

    directory_name = address[: address.find(sep)]
    LOG.d("directory_name %s", directory_name)

    directory = Directory.get_by(name=directory_name)
    if not directory:
        return None

    user: User = directory.user
    if user.disabled:
        LOG.i("Disabled %s can't create new alias with directory", user)
        return None

    if not user.can_create_new_alias():
        LOG.d(f"{user} can't create new directory alias {address}")
        if notify_user:
            send_cannot_create_directory_alias(user, address, directory_name)
        return None

    if directory.disabled:
        if notify_user:
            send_cannot_create_directory_alias_disabled(user, address, directory_name)
        return None

    return directory


def try_auto_create(address: str) -> Optional[Alias]:
    """Try to auto-create the alias using directory or catch-all domain"""
    # VERP for reply phase is {BOUNCE_PREFIX_FOR_REPLY_PHASE}+{email_log.id}+@{alias_domain}
    if address.startswith(f"{BOUNCE_PREFIX_FOR_REPLY_PHASE}+") and "+@" in address:
        LOG.e("alias %s can't start with %s", address, BOUNCE_PREFIX_FOR_REPLY_PHASE)
        return None

    # VERP for forward phase is BOUNCE_PREFIX + email_log.id + BOUNCE_SUFFIX
    if address.startswith(BOUNCE_PREFIX) and address.endswith(BOUNCE_SUFFIX):
        LOG.e("alias %s can't start with %s", address, BOUNCE_PREFIX)
        return None

    try:
        # NOT allow unicode for now
        validate_email(address, check_deliverability=False, allow_smtputf8=False)
    except EmailNotValidError:
        return None

    alias = try_auto_create_via_domain(address)
    if not alias:
        alias = try_auto_create_directory(address)

    return alias


def try_auto_create_directory(address: str) -> Optional[Alias]:
    """
    Try to create an alias with directory
    """
    directory = check_if_alias_can_be_auto_created_for_a_directory(
        address, notify_user=True
    )
    if not directory:
        return None

    try:
        LOG.d("create alias %s for directory %s", address, directory)

        mailboxes = directory.mailboxes

        alias = Alias.create(
            email=address,
            user_id=directory.user_id,
            directory_id=directory.id,
            mailbox_id=mailboxes[0].id,
        )
        if not directory.user.disable_automatic_alias_note:
            alias.note = f"Created by directory {directory.name}"
        Session.flush()
        for i in range(1, len(mailboxes)):
            AliasMailbox.create(
                alias_id=alias.id,
                mailbox_id=mailboxes[i].id,
            )

        Session.commit()
        return alias
    except AliasInTrashError:
        LOG.w(
            "Alias %s was deleted before, cannot auto-create using directory %s, user %s",
            address,
            directory.name,
            directory.user,
        )
        return None
    except IntegrityError:
        LOG.w("Alias %s already exists", address)
        Session.rollback()
        alias = Alias.get_by(email=address)
        return alias


def try_auto_create_via_domain(address: str) -> Optional[Alias]:
    """Try to create an alias with catch-all or auto-create rules on custom domain"""
    can_create = check_if_alias_can_be_auto_created_for_custom_domain(address)
    if not can_create:
        return None
    custom_domain, rule = can_create

    if rule:
        alias_note = f"Created by rule {rule.order} with regex {rule.regex}"
        mailboxes = rule.mailboxes
    else:
        alias_note = "Created by catchall option"
        mailboxes = custom_domain.mailboxes

    # a rule can have 0 mailboxes. Happened when a mailbox is deleted
    if not mailboxes:
        LOG.d(
            "use %s default mailbox for %s %s",
            custom_domain.user,
            address,
            custom_domain,
        )
        mailboxes = [custom_domain.user.default_mailbox]

    try:
        LOG.d("create alias %s for domain %s", address, custom_domain)
        alias = Alias.create(
            email=address,
            user_id=custom_domain.user_id,
            custom_domain_id=custom_domain.id,
            automatic_creation=True,
            mailbox_id=mailboxes[0].id,
        )
        if not custom_domain.user.disable_automatic_alias_note:
            alias.note = alias_note
        Session.flush()
        for i in range(1, len(mailboxes)):
            AliasMailbox.create(
                alias_id=alias.id,
                mailbox_id=mailboxes[i].id,
            )
        Session.commit()
        return alias
    except AliasInTrashError:
        LOG.w(
            "Alias %s was deleted before, cannot auto-create using domain catch-all %s, user %s",
            address,
            custom_domain,
            custom_domain.user,
        )
        return None
    except IntegrityError:
        LOG.w("Alias %s already exists", address)
        Session.rollback()
        alias = Alias.get_by(email=address)
        return alias
    except DataError:
        LOG.w("Cannot create alias %s", address)
        Session.rollback()
        return None


def delete_alias(alias: Alias, user: User):
    """
    Delete an alias and add it to either global or domain trash
    Should be used instead of Alias.delete, DomainDeletedAlias.create, DeletedAlias.create
    """
    # save deleted alias to either global or domain trash
    if alias.custom_domain_id:
        if not DomainDeletedAlias.get_by(
            email=alias.email, domain_id=alias.custom_domain_id
        ):
            LOG.d("add %s to domain %s trash", alias, alias.custom_domain_id)
            Session.add(
                DomainDeletedAlias(
                    user_id=user.id,
                    email=alias.email,
                    domain_id=alias.custom_domain_id,
                )
            )
            Session.commit()

    else:
        if not DeletedAlias.get_by(email=alias.email):
            LOG.d("add %s to global trash", alias)
            Session.add(DeletedAlias(email=alias.email))
            Session.commit()

    LOG.i("delete alias %s", alias)
    Alias.filter(Alias.id == alias.id).delete()
    Session.commit()


def aliases_for_mailbox(mailbox: Mailbox) -> [Alias]:
    """
    get list of aliases for a given mailbox
    """
    ret = set(Alias.filter(Alias.mailbox_id == mailbox.id).all())

    for alias in (
        Session.query(Alias)
        .join(AliasMailbox, Alias.id == AliasMailbox.alias_id)
        .filter(AliasMailbox.mailbox_id == mailbox.id)
    ):
        ret.add(alias)

    return list(ret)


def nb_email_log_for_mailbox(mailbox: Mailbox):
    aliases = aliases_for_mailbox(mailbox)
    alias_ids = [alias.id for alias in aliases]
    return (
        Session.query(EmailLog)
        .join(Contact, EmailLog.contact_id == Contact.id)
        .filter(Contact.alias_id.in_(alias_ids))
        .count()
    )


# Only lowercase letters, numbers, dots (.), dashes (-) and underscores (_) are currently supported
_ALIAS_PREFIX_PATTERN = r"[0-9a-z-_.]{1,}"


def check_alias_prefix(alias_prefix) -> bool:
    if len(alias_prefix) > 40:
        return False

    if re.fullmatch(_ALIAS_PREFIX_PATTERN, alias_prefix) is None:
        return False

    return True

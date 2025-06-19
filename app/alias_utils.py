import csv
import re
from dataclasses import dataclass
from io import StringIO
from typing import Optional, Tuple

from email_validator import validate_email, EmailNotValidError
from flask import make_response
from sqlalchemy.exc import IntegrityError, DataError

from app.alias_audit_log_utils import AliasAuditLogAction, emit_alias_audit_log
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
    send_email,
    render,
    sl_formataddr,
)
from app.errors import AliasInTrashError
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import (
    AliasDeleted,
    AliasStatusChanged,
    EventContent,
    AliasCreated,
    AliasNoteChanged,
)
from app.log import LOG
from app.models import (
    Alias,
    CustomDomain,
    Directory,
    User,
    DomainDeletedAlias,
    AliasMailbox,
    Mailbox,
    EmailLog,
    Contact,
    AutoCreateRule,
    AliasUsedOn,
    ClientUser,
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
        LOG.i(f"Not creating alias for {address} because email is invalid")
        return None

    domain_and_rule = check_if_alias_can_be_auto_created_for_custom_domain(
        address, notify_user=notify_user
    )
    if DomainDeletedAlias.get_by(email=address):
        LOG.i(
            f"Not creating alias for {address} because it was previously deleted for this domain"
        )
        return None
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
        LOG.i(
            f"Cannot auto-create custom domain alias for {address} because there's no custom domain for {alias_domain}"
        )
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
            LOG.i(
                f"Cannot create alias {address} for domain {custom_domain} because it has no catch-all and no rules"
            )
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
            LOG.d(f"No rule matches auto-create {address} for domain {custom_domain}")
            return None
    LOG.d(f"User {custom_domain.user} will create alias {address} via catchall")

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
        LOG.info(f"Cannot auto-create {address} since it has no directory separator")
        return None

    directory_name = address[: address.find(sep)]
    LOG.d("directory_name %s", directory_name)

    directory = Directory.get_by(name=directory_name)
    if not directory:
        LOG.info(
            f"Cannot auto-create {address} because there is no directory for {directory_name}"
        )
        return None

    user: User = directory.user
    if user.disabled:
        LOG.i("Disabled %s can't create new alias with directory", user)
        return None

    if not user.can_create_new_alias():
        LOG.d(
            f"{user} can't create new directory alias {address} because user cannot create aliases"
        )
        if notify_user:
            send_cannot_create_directory_alias(user, address, directory_name)
        return None

    if directory.disabled:
        LOG.d(
            f"{user} can't create new directory alias {address} bcause directory is disabled"
        )
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

        LOG.i(f"User {directory.user} created alias {alias} via directory {directory}")
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
        LOG.d(
            f"User {custom_domain.user} created alias {alias} via domain {custom_domain}"
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


def aliases_for_mailbox(mailbox: Mailbox) -> [Alias]:
    """
    get list of aliases for a given mailbox
    """
    ret = set(
        Alias.filter(Alias.mailbox_id == mailbox.id, Alias.delete_on == None).all()  # noqa: E711
    )

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


def alias_export_csv(user, csv_direct_export=False):
    """
    Get user aliases as importable CSV file
    Output:
        Importable CSV file

    """
    data = [["alias", "note", "enabled", "mailboxes"]]
    for alias in Alias.filter_by(user_id=user.id, delete_on=None).all():  # type: Alias
        # Always put the main mailbox first
        # It is seen a primary while importing
        alias_mailboxes = alias.mailboxes
        alias_mailboxes.insert(
            0, alias_mailboxes.pop(alias_mailboxes.index(alias.mailbox))
        )

        mailboxes = " ".join([mailbox.email for mailbox in alias_mailboxes])
        data.append([alias.email, alias.note, alias.enabled, mailboxes])

    si = StringIO()
    cw = csv.writer(si)
    cw.writerows(data)
    if csv_direct_export:
        return si.getvalue()
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=aliases.csv"
    output.headers["Content-type"] = "text/csv"
    return output


def transfer_alias(alias: Alias, new_user: User, new_mailboxes: [Mailbox]):
    # cannot transfer alias which is used for receiving newsletter
    if User.get_by(newsletter_alias_id=alias.id):
        raise Exception("Cannot transfer alias that's used to receive newsletter")

    # update user_id
    Session.query(Contact).filter(Contact.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    Session.query(AliasUsedOn).filter(AliasUsedOn.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    Session.query(ClientUser).filter(ClientUser.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    # remove existing mailboxes from the alias
    Session.query(AliasMailbox).filter(AliasMailbox.alias_id == alias.id).delete()

    # set mailboxes
    alias.mailbox_id = new_mailboxes.pop().id
    for mb in new_mailboxes:
        AliasMailbox.create(alias_id=alias.id, mailbox_id=mb.id)

    # alias has never been transferred before
    if not alias.original_owner_id:
        alias.original_owner_id = alias.user_id

    # inform previous owner
    old_user = alias.user
    send_email(
        old_user.email,
        f"Alias {alias.email} has been received",
        render(
            "transactional/alias-transferred.txt",
            user=old_user,
            alias=alias,
        ),
        render(
            "transactional/alias-transferred.html",
            user=old_user,
            alias=alias,
        ),
    )

    # now the alias belongs to the new user
    alias.user_id = new_user.id

    # set some fields back to default
    alias.disable_pgp = False
    alias.pinned = False

    emit_alias_audit_log(
        alias=alias,
        action=AliasAuditLogAction.TransferredAlias,
        message=f"Lost ownership of alias due to alias transfer confirmed. New owner is {new_user.id}",
        user_id=old_user.id,
    )
    EventDispatcher.send_event(
        old_user,
        EventContent(
            alias_deleted=AliasDeleted(
                id=alias.id,
                email=alias.email,
            )
        ),
    )

    emit_alias_audit_log(
        alias=alias,
        action=AliasAuditLogAction.AcceptTransferAlias,
        message=f"Accepted alias transfer from user {old_user.id}",
        user_id=new_user.id,
    )
    EventDispatcher.send_event(
        new_user,
        EventContent(
            alias_created=AliasCreated(
                id=alias.id,
                email=alias.email,
                note=alias.note,
                enabled=alias.enabled,
                created_at=int(alias.created_at.timestamp),
            )
        ),
    )

    Session.commit()


def change_alias_status(
    alias: Alias, enabled: bool, message: Optional[str] = None, commit: bool = False
):
    LOG.i(f"Changing alias {alias} enabled to {enabled}")
    alias.enabled = enabled

    event = AliasStatusChanged(
        id=alias.id,
        email=alias.email,
        enabled=enabled,
        created_at=int(alias.created_at.timestamp),
    )
    EventDispatcher.send_event(alias.user, EventContent(alias_status_change=event))
    audit_log_message = f"Set alias status to {enabled}"
    if message is not None:
        audit_log_message += f". {message}"
    emit_alias_audit_log(
        alias, AliasAuditLogAction.ChangeAliasStatus, audit_log_message
    )

    if commit:
        Session.commit()


def change_alias_note(alias: Alias, note: str, commit: bool = False):
    LOG.i(f"Changing alias {alias} note.")

    alias.note = note
    # TODO: acasajus Enable back after July 1st 2025
    if False:
        event = AliasNoteChanged(
            id=alias.id,
            email=alias.email,
            note=note,
        )

        EventDispatcher.send_event(alias.user, EventContent(alias_note_changed=event))
    else:
        LOG.i("Skipping sending event for now")

    if commit:
        Session.commit()


@dataclass
class AliasRecipientName:
    name: str
    message: Optional[str] = None


def get_alias_recipient_name(alias: Alias) -> AliasRecipientName:
    """
    Logic:
    1. If alias has name, use it
    2. If alias has custom domain, and custom domain has name, use it
    3. Otherwise, use the alias email as the recipient
    """
    if alias.name:
        return AliasRecipientName(
            name=sl_formataddr((alias.name, alias.email)),
            message=f"Put alias name {alias.name} in from header",
        )
    elif alias.custom_domain:
        if alias.custom_domain.name:
            return AliasRecipientName(
                name=sl_formataddr((alias.custom_domain.name, alias.email)),
                message=f"Put domain default alias name {alias.custom_domain.name} in from header",
            )
    return AliasRecipientName(name=alias.email)

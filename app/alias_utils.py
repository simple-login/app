import re
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.email_utils import (
    get_email_domain_part,
    send_cannot_create_directory_alias,
    send_cannot_create_domain_alias,
    can_create_directory_for_address,
)
from app.errors import AliasInTrashError
from app.extensions import db
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
)


def try_auto_create(address: str) -> Optional[Alias]:
    """Try to auto-create the alias using directory or catch-all domain"""
    alias = try_auto_create_catch_all_domain(address)
    if not alias:
        alias = try_auto_create_directory(address)

    return alias


def try_auto_create_directory(address: str) -> Optional[Alias]:
    """
    Try to create an alias with directory
    """
    # check if alias belongs to a directory, ie having directory/anything@EMAIL_DOMAIN format
    if can_create_directory_for_address(address):
        # if there's no directory separator in the alias, no way to auto-create it
        if "/" not in address and "+" not in address and "#" not in address:
            return None

        # alias contains one of the 3 special directory separator: "/", "+" or "#"
        if "/" in address:
            sep = "/"
        elif "+" in address:
            sep = "+"
        else:
            sep = "#"

        directory_name = address[: address.find(sep)]
        LOG.d("directory_name %s", directory_name)

        directory = Directory.get_by(name=directory_name)
        if not directory:
            return None

        dir_user: User = directory.user

        if not dir_user.can_create_new_alias():
            send_cannot_create_directory_alias(dir_user, address, directory_name)
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
            db.session.flush()
            for i in range(1, len(mailboxes)):
                AliasMailbox.create(
                    alias_id=alias.id,
                    mailbox_id=mailboxes[i].id,
                )

            db.session.commit()
            return alias
        except AliasInTrashError:
            LOG.warning(
                "Alias %s was deleted before, cannot auto-create using directory %s, user %s",
                address,
                directory_name,
                dir_user,
            )
            return None
        except IntegrityError:
            LOG.warning("Alias %s already exists", address)
            db.session.rollback()
            alias = Alias.get_by(email=address)
            return alias


def try_auto_create_catch_all_domain(address: str) -> Optional[Alias]:
    """Try to create an alias with catch-all domain"""

    # try to create alias on-the-fly with custom-domain catch-all feature
    # check if alias is custom-domain alias and if the custom-domain has catch-all enabled
    alias_domain = get_email_domain_part(address)
    custom_domain: CustomDomain = CustomDomain.get_by(domain=alias_domain)

    if not custom_domain:
        return None

    # custom_domain exists
    if not custom_domain.catch_all:
        return None

    # custom_domain has catch-all enabled
    domain_user: User = custom_domain.user

    if not domain_user.can_create_new_alias():
        send_cannot_create_domain_alias(domain_user, address, alias_domain)
        return None

    try:
        LOG.d("create alias %s for domain %s", address, custom_domain)
        mailboxes = custom_domain.mailboxes
        alias = Alias.create(
            email=address,
            user_id=custom_domain.user_id,
            custom_domain_id=custom_domain.id,
            automatic_creation=True,
            mailbox_id=mailboxes[0].id,
        )
        db.session.flush()
        for i in range(1, len(mailboxes)):
            AliasMailbox.create(
                alias_id=alias.id,
                mailbox_id=mailboxes[i].id,
            )
        db.session.commit()
        return alias
    except AliasInTrashError:
        LOG.warning(
            "Alias %s was deleted before, cannot auto-create using domain catch-all %s, user %s",
            address,
            custom_domain,
            domain_user,
        )
        return None
    except IntegrityError:
        LOG.warning("Alias %s already exists", address)
        db.session.rollback()
        alias = Alias.get_by(email=address)
        return alias


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
            LOG.debug("add %s to domain %s trash", alias, alias.custom_domain_id)
            db.session.add(
                DomainDeletedAlias(
                    user_id=user.id, email=alias.email, domain_id=alias.custom_domain_id
                )
            )
            db.session.commit()
    else:
        if not DeletedAlias.get_by(email=alias.email):
            LOG.d("add %s to global trash", alias)
            db.session.add(DeletedAlias(email=alias.email))
            db.session.commit()

    Alias.query.filter(Alias.id == alias.id).delete()
    db.session.commit()


def aliases_for_mailbox(mailbox: Mailbox) -> [Alias]:
    """
    get list of aliases for a given mailbox
    """
    ret = set(Alias.query.filter(Alias.mailbox_id == mailbox.id).all())

    for alias in (
        db.session.query(Alias)
        .join(AliasMailbox, Alias.id == AliasMailbox.alias_id)
        .filter(AliasMailbox.mailbox_id == mailbox.id)
    ):
        ret.add(alias)

    return list(ret)


def nb_email_log_for_mailbox(mailbox: Mailbox):
    aliases = aliases_for_mailbox(mailbox)
    alias_ids = [alias.id for alias in aliases]
    return (
        db.session.query(EmailLog)
        .join(Contact, EmailLog.contact_id == Contact.id)
        .filter(Contact.alias_id.in_(alias_ids))
        .count()
    )


# Only lowercase letters, numbers, dashes (-) and underscores (_) are currently supported
_ALIAS_PREFIX_PATTERN = r"[0-9a-z-_]{1,}"


def check_alias_prefix(alias_prefix) -> bool:
    if re.fullmatch(_ALIAS_PREFIX_PATTERN, alias_prefix) is None:
        return False

    return True

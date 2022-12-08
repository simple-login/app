import csv

import requests

from app import s3
from app.db import Session
from app.email_utils import get_email_domain_part
from app.models import (
    Alias,
    AliasMailbox,
    BatchImport,
    CustomDomain,
    DeletedAlias,
    DomainDeletedAlias,
    Mailbox,
    User,
)
from app.utils import sanitize_email
from .log import LOG


def handle_batch_import(batch_import: BatchImport):
    user = batch_import.user

    batch_import.processed = True
    Session.commit()

    LOG.d("Start batch import for %s %s", batch_import, user)
    file_url = s3.get_url(batch_import.file.path)

    LOG.d("Download file %s from %s", batch_import.file, file_url)
    r = requests.get(file_url)
    lines = [line.decode() for line in r.iter_lines()]

    import_from_csv(batch_import, user, lines)


def import_from_csv(batch_import: BatchImport, user: User, lines):
    reader = csv.DictReader(lines)

    for row in reader:
        try:
            full_alias = sanitize_email(row["alias"])
            note = row["note"]
        except KeyError:
            LOG.w("Cannot parse row %s", row)
            continue

        alias_domain = get_email_domain_part(full_alias)
        custom_domain = CustomDomain.get_by(domain=alias_domain)

        if (
            not custom_domain
            or not custom_domain.ownership_verified
            or custom_domain.user_id != user.id
        ):
            LOG.d("domain %s can't be used %s", alias_domain, user)
            continue

        if (
            Alias.get_by(email=full_alias)
            or DeletedAlias.get_by(email=full_alias)
            or DomainDeletedAlias.get_by(email=full_alias)
        ):
            LOG.d("alias already used %s", full_alias)
            continue

        mailboxes = []

        if "mailboxes" in row:
            for mailbox_email in row["mailboxes"].split():
                mailbox_email = sanitize_email(mailbox_email)
                mailbox = Mailbox.get_by(email=mailbox_email)

                if not mailbox or not mailbox.verified or mailbox.user_id != user.id:
                    LOG.d("mailbox %s can't be used %s", mailbox, user)
                    continue

                mailboxes.append(mailbox.id)

        if len(mailboxes) == 0:
            mailboxes = [user.default_mailbox_id]

        if user.can_create_new_alias():
            alias = Alias.create(
                user_id=user.id,
                email=full_alias,
                note=note,
                mailbox_id=mailboxes[0],
                custom_domain_id=custom_domain.id,
                batch_import_id=batch_import.id,
                commit=True,
            )
            LOG.d("Create %s", alias)

            for i in range(1, len(mailboxes)):
                AliasMailbox.create(
                    alias_id=alias.id, mailbox_id=mailboxes[i], commit=True
                )
                Session.commit()
                LOG.d("Add %s to mailbox %s", alias, mailboxes[i])

import zipfile
from random import random

from app.db import Session
from app.jobs.export_user_data_job import ExportUserDataJob
from app.models import (
    Contact,
    Directory,
    DirectoryMailbox,
    RefusedEmail,
    CustomDomain,
    EmailLog,
    Alias,
)
from tests.utils import create_new_user, random_token


def test_model_retrieval_and_serialization():
    user = create_new_user()
    job = ExportUserDataJob(user)
    ExportUserDataJob._model_to_dict(user)

    # Aliases
    aliases = job._get_aliases()
    assert len(aliases) == 1
    ExportUserDataJob._model_to_dict(aliases[0])

    # Mailboxes
    mailboxes = job._get_mailboxes()
    assert len(mailboxes) == 1
    ExportUserDataJob._model_to_dict(mailboxes[0])

    # Contacts
    alias = aliases[0]
    contact = Contact.create(
        website_email=f"marketing-{random()}@example.com",
        reply_email=f"reply-{random()}@a.b",
        alias_id=alias.id,
        user_id=alias.user_id,
        commit=True,
    )
    contacts = job._get_contacts()
    assert len(contacts) == 1
    assert contact.id == contacts[0].id
    ExportUserDataJob._model_to_dict(contacts[0])

    # Directories
    dir_name = random_token()
    directory = Directory.create(name=dir_name, user_id=user.id, flush=True)
    DirectoryMailbox.create(
        directory_id=directory.id, mailbox_id=user.default_mailbox_id, flush=True
    )
    directories = job._get_directories()
    assert len(directories) == 1
    assert directory.id == directories[0].id
    ExportUserDataJob._model_to_dict(directories[0])

    # CustomDomain
    custom_domain = CustomDomain.create(
        domain=f"{random()}.com", user_id=user.id, commit=True
    )
    domains = job._get_domains()
    assert len(domains) == 1
    assert custom_domain.id == domains[0].id
    ExportUserDataJob._model_to_dict(domains[0])

    # RefusedEmails
    refused_email = RefusedEmail.create(
        path=None,
        full_report_path=f"some/path/{random()}",
        user_id=alias.user_id,
        commit=True,
    )
    refused_emails = job._get_refused_emails()
    assert len(refused_emails) == 1
    assert refused_email.id == refused_emails[0].id
    ExportUserDataJob._model_to_dict(refused_emails[0])

    # EmailLog
    email_log = EmailLog.create(
        user_id=user.id,
        refused_email_id=refused_email.id,
        mailbox_id=alias.mailbox.id,
        contact_id=contact.id,
        alias_id=alias.id,
        commit=True,
    )
    email_logs = job._get_email_logs()
    assert len(email_logs) == 1
    assert email_log.id == email_logs[0].id
    ExportUserDataJob._model_to_dict(email_logs[0])

    # Get zip
    memfile = job._build_zip()
    files_in_zip = set()
    with zipfile.ZipFile(memfile, "r") as zf:
        for file_info in zf.infolist():
            files_in_zip.add(file_info.filename)
            assert file_info.file_size > 0
    expected_files_in_zip = set(
        (
            "user.json",
            "aliases.json",
            "mailboxes.json",
            "contacts.json",
            "directories.json",
            "domains.json",
            "email_logs.json",
            # "refused_emails.json",
        )
    )
    assert expected_files_in_zip == files_in_zip


def test_model_retrieval_pagination():
    user = create_new_user()
    aliases = Session.query(Alias).filter(Alias.user_id == user.id).all()
    for _i in range(5):
        aliases.append(Alias.create_new_random(user))
        Session.commit()
        found_aliases = ExportUserDataJob(user)._get_paginated_model(Alias, 2)
        assert len(found_aliases) == len(aliases)


def test_send_report():
    user = create_new_user()
    ExportUserDataJob(user).run()


def test_store_and_retrieve():
    user = create_new_user()
    export_job = ExportUserDataJob(user)
    db_job = export_job.store_job_in_db()
    assert db_job is not None
    export_from_from_db = ExportUserDataJob.create_from_job(db_job)
    assert export_job._user.id == export_from_from_db._user.id


def test_double_store_fails():
    user = create_new_user()
    export_job = ExportUserDataJob(user)
    db_job = export_job.store_job_in_db()
    assert db_job is not None
    retry = export_job.store_job_in_db()
    assert retry is None

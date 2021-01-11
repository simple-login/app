"""
Run scheduled jobs.
Not meant for running job at precise time (+- 1h)
"""
import csv
import time

import arrow
import requests

from app import s3
from app.config import (
    JOB_ONBOARDING_1,
    JOB_ONBOARDING_2,
    JOB_ONBOARDING_4,
    JOB_BATCH_IMPORT,
)
from app.email_utils import (
    send_email,
    render,
    get_email_domain_part,
)
from app.utils import sanitize_email
from app.extensions import db
from app.log import LOG
from app.models import (
    User,
    Job,
    BatchImport,
    Alias,
    DeletedAlias,
    DomainDeletedAlias,
    CustomDomain,
)
from server import create_app


# fix the database connection leak issue
# use this method instead of create_app
def new_app():
    app = create_app()

    @app.teardown_appcontext
    def shutdown_session(response_or_exc):
        # same as shutdown_session() in flask-sqlalchemy but this is not enough
        db.session.remove()

        # dispose the engine too
        db.engine.dispose()

    return app


def onboarding_send_from_alias(user):
    to_email, unsubscribe_link, via_email = user.get_communication_email()
    if not to_email:
        return

    send_email(
        to_email,
        "SimpleLogin Tip: Send emails from your alias",
        render("com/onboarding/send-from-alias.txt", user=user, to_email=to_email),
        render("com/onboarding/send-from-alias.html", user=user, to_email=to_email),
        unsubscribe_link,
        via_email,
    )


def onboarding_pgp(user):
    to_email, unsubscribe_link, via_email = user.get_communication_email()
    if not to_email:
        return

    send_email(
        to_email,
        "SimpleLogin Tip: Secure your emails with PGP",
        render("com/onboarding/pgp.txt", user=user, to_email=to_email),
        render("com/onboarding/pgp.html", user=user, to_email=to_email),
        unsubscribe_link,
        via_email,
    )


def onboarding_browser_extension(user):
    to_email, unsubscribe_link, via_email = user.get_communication_email()
    if not to_email:
        return

    send_email(
        to_email,
        "SimpleLogin Tip: Chrome/Firefox/Safari extensions and Android/iOS apps",
        render("com/onboarding/browser-extension.txt", user=user, to_email=to_email),
        render("com/onboarding/browser-extension.html", user=user, to_email=to_email),
        unsubscribe_link,
        via_email,
    )


def onboarding_mailbox(user):
    to_email, unsubscribe_link, via_email = user.get_communication_email()
    if not to_email:
        return

    send_email(
        to_email,
        "SimpleLogin Tip: Multiple mailboxes",
        render("com/onboarding/mailbox.txt", user=user, to_email=to_email),
        render("com/onboarding/mailbox.html", user=user, to_email=to_email),
        unsubscribe_link,
        via_email,
    )


def handle_batch_import(batch_import: BatchImport):
    user = batch_import.user

    batch_import.processed = True
    db.session.commit()

    LOG.debug("Start batch import for %s %s", batch_import, user)
    file_url = s3.get_url(batch_import.file.path)

    LOG.d("Download file %s from %s", batch_import.file, file_url)
    r = requests.get(file_url)
    lines = [line.decode() for line in r.iter_lines()]
    reader = csv.DictReader(lines)

    for row in reader:
        try:
            full_alias = sanitize_email(row["alias"])
            note = row["note"]
        except KeyError:
            LOG.warning("Cannot parse row %s", row)
            continue

        alias_domain = get_email_domain_part(full_alias)
        custom_domain = CustomDomain.get_by(domain=alias_domain)

        if (
            not custom_domain
            or not custom_domain.verified
            or custom_domain.user_id != user.id
        ):
            LOG.debug("domain %s can't be used %s", alias_domain, user)
            continue

        if (
            Alias.get_by(email=full_alias)
            or DeletedAlias.get_by(email=full_alias)
            or DomainDeletedAlias.get_by(email=full_alias)
        ):
            LOG.d("alias already used %s", full_alias)
            continue

        alias = Alias.create(
            user_id=user.id,
            email=full_alias,
            note=note,
            mailbox_id=user.default_mailbox_id,
            custom_domain_id=custom_domain.id,
            batch_import_id=batch_import.id,
        )
        db.session.commit()
        LOG.d("Create %s", alias)


if __name__ == "__main__":
    while True:
        # run a job 1h earlier or later is not a big deal ...
        min_dt = arrow.now().shift(hours=-1)
        max_dt = arrow.now().shift(hours=1)

        app = new_app()

        with app.app_context():
            for job in Job.query.filter(
                Job.taken.is_(False), Job.run_at > min_dt, Job.run_at <= max_dt
            ).all():
                LOG.d("Take job %s", job)

                # mark the job as taken, whether it will be executed successfully or not
                job.taken = True
                db.session.commit()

                if job.name == JOB_ONBOARDING_1:
                    user_id = job.payload.get("user_id")
                    user = User.get(user_id)

                    # user might delete their account in the meantime
                    # or disable the notification
                    if user and user.notification and user.activated:
                        LOG.d("send onboarding send-from-alias email to user %s", user)
                        onboarding_send_from_alias(user)
                elif job.name == JOB_ONBOARDING_2:
                    user_id = job.payload.get("user_id")
                    user = User.get(user_id)

                    # user might delete their account in the meantime
                    # or disable the notification
                    if user and user.notification and user.activated:
                        LOG.d("send onboarding mailbox email to user %s", user)
                        onboarding_mailbox(user)
                elif job.name == JOB_ONBOARDING_4:
                    user_id = job.payload.get("user_id")
                    user = User.get(user_id)

                    # user might delete their account in the meantime
                    # or disable the notification
                    if user and user.notification and user.activated:
                        LOG.d("send onboarding pgp email to user %s", user)
                        onboarding_pgp(user)

                elif job.name == JOB_BATCH_IMPORT:
                    batch_import_id = job.payload.get("batch_import_id")
                    batch_import = BatchImport.get(batch_import_id)
                    handle_batch_import(batch_import)

                else:
                    LOG.exception("Unknown job name %s", job.name)

        time.sleep(10)

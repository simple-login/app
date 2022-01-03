"""
Run scheduled jobs.
Not meant for running job at precise time (+- 1h)
"""
import time

import arrow

from app.config import (
    JOB_ONBOARDING_1,
    JOB_ONBOARDING_2,
    JOB_ONBOARDING_4,
    JOB_BATCH_IMPORT,
    JOB_DELETE_ACCOUNT,
    JOB_DELETE_MAILBOX,
    JOB_DELETE_DOMAIN,
)
from app.db import Session
from app.email_utils import (
    send_email,
    render,
)
from app.import_utils import handle_batch_import
from app.log import LOG
from app.models import User, Job, BatchImport, Mailbox, CustomDomain
from server import create_light_app


def onboarding_send_from_alias(user):
    to_email, unsubscribe_link, via_email = user.get_communication_email()
    if not to_email:
        return

    send_email(
        to_email,
        "SimpleLogin Tip: Send emails from your alias",
        render("com/onboarding/send-from-alias.txt.j2", user=user, to_email=to_email),
        render("com/onboarding/send-from-alias.html", user=user, to_email=to_email),
        unsubscribe_link,
        via_email,
        retries=3,
        ignore_smtp_error=True,
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
        retries=3,
        ignore_smtp_error=True,
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
        retries=3,
        ignore_smtp_error=True,
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
        retries=3,
        ignore_smtp_error=True,
    )


if __name__ == "__main__":
    while True:
        # wrap in an app context to benefit from app setup like database cleanup, sentry integration, etc
        with create_light_app().app_context():
            # run a job 1h earlier or later is not a big deal ...
            min_dt = arrow.now().shift(hours=-1)
            max_dt = arrow.now().shift(hours=1)

            for job in Job.filter(
                Job.taken.is_(False), Job.run_at > min_dt, Job.run_at <= max_dt
            ).all():
                LOG.d("Take job %s", job)

                # mark the job as taken, whether it will be executed successfully or not
                job.taken = True
                Session.commit()

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
                elif job.name == JOB_DELETE_ACCOUNT:
                    user_id = job.payload.get("user_id")
                    user = User.get(user_id)

                    if not user:
                        LOG.i("No user found for %s", user_id)
                        continue

                    user_email = user.email
                    LOG.w("Delete user %s", user)
                    User.delete(user.id)
                    Session.commit()

                    send_email(
                        user_email,
                        "Your SimpleLogin account has been deleted",
                        render("transactional/account-delete.txt"),
                        render("transactional/account-delete.html"),
                        retries=3,
                    )
                elif job.name == JOB_DELETE_MAILBOX:
                    mailbox_id = job.payload.get("mailbox_id")
                    mailbox = Mailbox.get(mailbox_id)
                    if not mailbox:
                        continue

                    mailbox_email = mailbox.email
                    user = mailbox.user

                    Mailbox.delete(mailbox_id)
                    Session.commit()
                    LOG.d("Mailbox %s %s deleted", mailbox_id, mailbox_email)

                    send_email(
                        user.email,
                        f"Your mailbox {mailbox_email} has been deleted",
                        f"""Mailbox {mailbox_email} along with its aliases are deleted successfully.
Regards,
SimpleLogin team.
""",
                        retries=3,
                    )

                elif job.name == JOB_DELETE_DOMAIN:
                    custom_domain_id = job.payload.get("custom_domain_id")
                    custom_domain = CustomDomain.get(custom_domain_id)
                    if not custom_domain:
                        continue

                    domain_name = custom_domain.domain
                    user = custom_domain.user

                    CustomDomain.delete(custom_domain.id)
                    Session.commit()

                    LOG.d("Domain %s deleted", domain_name)

                    send_email(
                        user.email,
                        f"Your domain {domain_name} has been deleted",
                        f"""Domain {domain_name} along with its aliases are deleted successfully.

Regards,
SimpleLogin team.
""",
                        retries=3,
                    )

                else:
                    LOG.e("Unknown job name %s", job.name)

            time.sleep(10)

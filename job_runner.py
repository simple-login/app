"""
Run scheduled jobs.
Not meant for running job at precise time (+- 1h)
"""
import time
from typing import List, Optional

import arrow
from sqlalchemy.sql.expression import or_, and_

from app import config
from app.db import Session
from app.email_utils import (
    send_email,
    render,
)
from app.events.event_dispatcher import PostgresDispatcher
from app.import_utils import handle_batch_import
from app.jobs.event_jobs import send_alias_creation_events_for_user
from app.jobs.export_user_data_job import ExportUserDataJob
from app.log import LOG
from app.models import User, Job, BatchImport, Mailbox, CustomDomain, JobState
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from server import create_light_app


def onboarding_send_from_alias(user):
    comm_email, unsubscribe_link, via_email = user.get_communication_email()
    if not comm_email:
        return

    send_email(
        comm_email,
        "SimpleLogin Tip: Send emails from your alias",
        render(
            "com/onboarding/send-from-alias.txt.j2",
            user=user,
            to_email=comm_email,
        ),
        render("com/onboarding/send-from-alias.html", user=user, to_email=comm_email),
        unsubscribe_link,
        via_email,
        retries=3,
        ignore_smtp_error=True,
    )


def onboarding_pgp(user):
    comm_email, unsubscribe_link, via_email = user.get_communication_email()
    if not comm_email:
        return

    send_email(
        comm_email,
        "SimpleLogin Tip: Secure your emails with PGP",
        render("com/onboarding/pgp.txt", user=user, to_email=comm_email),
        render("com/onboarding/pgp.html", user=user, to_email=comm_email),
        unsubscribe_link,
        via_email,
        retries=3,
        ignore_smtp_error=True,
    )


def onboarding_browser_extension(user):
    comm_email, unsubscribe_link, via_email = user.get_communication_email()
    if not comm_email:
        return

    send_email(
        comm_email,
        "SimpleLogin Tip: Chrome/Firefox/Safari extensions and Android/iOS apps",
        render(
            "com/onboarding/browser-extension.txt",
            user=user,
            to_email=comm_email,
        ),
        render(
            "com/onboarding/browser-extension.html",
            user=user,
            to_email=comm_email,
        ),
        unsubscribe_link,
        via_email,
        retries=3,
        ignore_smtp_error=True,
    )


def onboarding_mailbox(user):
    comm_email, unsubscribe_link, via_email = user.get_communication_email()
    if not comm_email:
        return

    send_email(
        comm_email,
        "SimpleLogin Tip: Multiple mailboxes",
        render("com/onboarding/mailbox.txt", user=user, to_email=comm_email),
        render("com/onboarding/mailbox.html", user=user, to_email=comm_email),
        unsubscribe_link,
        via_email,
        retries=3,
        ignore_smtp_error=True,
    )


def welcome_proton(user):
    comm_email, _, _ = user.get_communication_email()
    if not comm_email:
        return

    send_email(
        comm_email,
        "Welcome to SimpleLogin, an email masking service provided by Proton",
        render(
            "com/onboarding/welcome-proton-user.txt.jinja2",
            user=user,
            to_email=comm_email,
        ),
        render(
            "com/onboarding/welcome-proton-user.html",
            user=user,
            to_email=comm_email,
        ),
        retries=3,
        ignore_smtp_error=True,
    )


def delete_mailbox_job(job: Job):
    mailbox_id = job.payload.get("mailbox_id")
    mailbox: Optional[Mailbox] = Mailbox.get(mailbox_id)
    if not mailbox:
        return

    transfer_mailbox_id = job.payload.get("transfer_mailbox_id")
    alias_transferred_to = None
    if transfer_mailbox_id:
        transfer_mailbox = Mailbox.get(transfer_mailbox_id)
        if transfer_mailbox:
            alias_transferred_to = transfer_mailbox.email

            for alias in mailbox.aliases:
                if alias.mailbox_id == mailbox.id:
                    alias.mailbox_id = transfer_mailbox.id
                    if transfer_mailbox in alias._mailboxes:
                        alias._mailboxes.remove(transfer_mailbox)
                else:
                    alias._mailboxes.remove(mailbox)
                    if transfer_mailbox not in alias._mailboxes:
                        alias._mailboxes.append(transfer_mailbox)
                Session.commit()

    mailbox_email = mailbox.email
    user = mailbox.user

    emit_user_audit_log(
        user_id=user.id,
        action=UserAuditLogAction.DeleteMailbox,
        message=f"Delete mailbox {mailbox.id} ({mailbox.email})",
    )
    Mailbox.delete(mailbox_id)
    Session.commit()
    LOG.d("Mailbox %s %s deleted", mailbox_id, mailbox_email)

    if alias_transferred_to:
        send_email(
            user.email,
            f"Your mailbox {mailbox_email} has been deleted",
            f"""Mailbox {mailbox_email} and its alias have been transferred to {alias_transferred_to}.
Regards,
SimpleLogin team.
""",
            retries=3,
        )
    else:
        send_email(
            user.email,
            f"Your mailbox {mailbox_email} has been deleted",
            f"""Mailbox {mailbox_email} along with its aliases have been deleted successfully.
Regards,
SimpleLogin team.
""",
            retries=3,
        )


def process_job(job: Job):
    if job.name == config.JOB_ONBOARDING_1:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)

        # user might delete their account in the meantime
        # or disable the notification
        if user and user.notification and user.activated:
            LOG.d("send onboarding send-from-alias email to user %s", user)
            onboarding_send_from_alias(user)
    elif job.name == config.JOB_ONBOARDING_2:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)

        # user might delete their account in the meantime
        # or disable the notification
        if user and user.notification and user.activated:
            LOG.d("send onboarding mailbox email to user %s", user)
            onboarding_mailbox(user)
    elif job.name == config.JOB_ONBOARDING_4:
        user_id = job.payload.get("user_id")
        user: User = User.get(user_id)

        # user might delete their account in the meantime
        # or disable the notification
        if user and user.notification and user.activated:
            # if user only has 1 mailbox which is Proton then do not send PGP onboarding email
            mailboxes = user.mailboxes()
            if len(mailboxes) == 1 and mailboxes[0].is_proton():
                LOG.d("Do not send onboarding PGP email to Proton mailbox")
            else:
                LOG.d("send onboarding pgp email to user %s", user)
                onboarding_pgp(user)

    elif job.name == config.JOB_BATCH_IMPORT:
        batch_import_id = job.payload.get("batch_import_id")
        batch_import = BatchImport.get(batch_import_id)
        handle_batch_import(batch_import)
    elif job.name == config.JOB_DELETE_ACCOUNT:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)

        if not user:
            LOG.i("No user found for %s", user_id)
            return

        user_email = user.email
        LOG.w("Delete user %s", user)
        send_email(
            user_email,
            "Your SimpleLogin account has been deleted",
            render("transactional/account-delete.txt", user=user),
            render("transactional/account-delete.html", user=user),
            retries=3,
        )
        User.delete(user.id)
        Session.commit()
    elif job.name == config.JOB_DELETE_MAILBOX:
        delete_mailbox_job(job)

    elif job.name == config.JOB_DELETE_DOMAIN:
        custom_domain_id = job.payload.get("custom_domain_id")
        custom_domain: Optional[CustomDomain] = CustomDomain.get(custom_domain_id)
        if not custom_domain:
            return

        domain_name = custom_domain.domain
        user = custom_domain.user

        custom_domain_partner_id = custom_domain.partner_id
        CustomDomain.delete(custom_domain.id)
        Session.commit()

        LOG.d("Domain %s deleted", domain_name)

        if custom_domain_partner_id is None:
            send_email(
                user.email,
                f"Your domain {domain_name} has been deleted",
                f"""Domain {domain_name} along with its aliases are deleted successfully.

    Regards,
    SimpleLogin team.
    """,
                retries=3,
            )
    elif job.name == config.JOB_SEND_USER_REPORT:
        export_job = ExportUserDataJob.create_from_job(job)
        if export_job:
            export_job.run()
    elif job.name == config.JOB_SEND_PROTON_WELCOME_1:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)
        if user and user.activated:
            LOG.d("Send proton welcome email to user %s", user)
            welcome_proton(user)
    elif job.name == config.JOB_SEND_ALIAS_CREATION_EVENTS:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)
        if user and user.activated:
            LOG.d(f"Sending alias creation events for {user}")
            send_alias_creation_events_for_user(
                user, dispatcher=PostgresDispatcher.get()
            )
    else:
        LOG.e("Unknown job name %s", job.name)


def get_jobs_to_run() -> List[Job]:
    # Get jobs that match all conditions:
    #  - Job.state == ready OR (Job.state == taken AND Job.taken_at < now - 30 mins AND Job.attempts < 5)
    #  - Job.run_at is Null OR Job.run_at < now + 10 mins
    taken_at_earliest = arrow.now().shift(minutes=-config.JOB_TAKEN_RETRY_WAIT_MINS)
    run_at_earliest = arrow.now().shift(minutes=+10)
    query = Job.filter(
        and_(
            or_(
                Job.state == JobState.ready.value,
                and_(
                    Job.state == JobState.taken.value,
                    Job.taken_at < taken_at_earliest,
                    Job.attempts < config.JOB_MAX_ATTEMPTS,
                ),
            ),
            or_(Job.run_at.is_(None), and_(Job.run_at <= run_at_earliest)),
        )
    )
    return query.all()


if __name__ == "__main__":
    while True:
        # wrap in an app context to benefit from app setup like database cleanup, sentry integration, etc
        with create_light_app().app_context():
            for job in get_jobs_to_run():
                LOG.d("Take job %s", job)

                # mark the job as taken, whether it will be executed successfully or not
                job.taken = True
                job.taken_at = arrow.now()
                job.state = JobState.taken.value
                job.attempts += 1
                Session.commit()
                process_job(job)

                job.state = JobState.done.value
                Session.commit()

            time.sleep(10)

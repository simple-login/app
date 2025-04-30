"""
Run scheduled jobs.
Not meant for running job at precise time (+- 1h)
"""

import time
from typing import List, Optional

import arrow
import newrelic.agent
from sqlalchemy.orm import Query
from sqlalchemy.orm.exc import ObjectDeletedError
from sqlalchemy.sql.expression import or_, and_

from app import config
from app.constants import JobType
from app.db import Session
from app.email_utils import (
    send_email,
    render,
)
from app.events.event_dispatcher import PostgresDispatcher
from app.import_utils import handle_batch_import
from app.jobs.event_jobs import send_alias_creation_events_for_user
from app.jobs.export_user_data_job import ExportUserDataJob
from app.jobs.send_event_job import SendEventToWebhookJob
from app.jobs.sync_subscription_job import SyncSubscriptionJob
from app.log import LOG
from app.models import User, Job, BatchImport, Mailbox, JobState
from app.monitor_utils import send_version_event
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from events.event_sink import HttpEventSink
from server import create_light_app
from tasks.delete_custom_domain_job import DeleteCustomDomainJob

_MAX_JOBS_PER_BATCH = 50


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
        user=user,
        action=UserAuditLogAction.DeleteMailbox,
        message=f"Delete mailbox {mailbox.id} ({mailbox.email})",
    )
    Mailbox.delete(mailbox_id)
    Session.commit()
    LOG.d("Mailbox %s %s deleted", mailbox_id, mailbox_email)

    if not job.payload.get("send_mail", True):
        return
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
    send_version_event("job_runner")
    if job.name == JobType.ONBOARDING_1.value:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)

        # user might delete their account in the meantime
        # or disable the notification
        if user and user.notification and user.activated:
            LOG.d("send onboarding send-from-alias email to user %s", user)
            onboarding_send_from_alias(user)
    elif job.name == JobType.ONBOARDING_2.value:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)

        # user might delete their account in the meantime
        # or disable the notification
        if user and user.notification and user.activated:
            LOG.d("send onboarding mailbox email to user %s", user)
            onboarding_mailbox(user)
    elif job.name == JobType.ONBOARDING_4.value:
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

    elif job.name == JobType.BATCH_IMPORT.value:
        batch_import_id = job.payload.get("batch_import_id")
        batch_import = BatchImport.get(batch_import_id)
        handle_batch_import(batch_import)
    elif job.name == JobType.DELETE_ACCOUNT.value:
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
    elif job.name == JobType.DELETE_MAILBOX.value:
        delete_mailbox_job(job)

    elif job.name == JobType.DELETE_DOMAIN.value:
        delete_job = DeleteCustomDomainJob.create_from_job(job)
        if delete_job:
            delete_job.run()

    elif job.name == JobType.SEND_USER_REPORT.value:
        export_job = ExportUserDataJob.create_from_job(job)
        if export_job:
            export_job.run()
    elif job.name == JobType.SEND_PROTON_WELCOME_1.value:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)
        if user and user.activated:
            LOG.d("Send proton welcome email to user %s", user)
            welcome_proton(user)
    elif job.name == JobType.SEND_ALIAS_CREATION_EVENTS.value:
        user_id = job.payload.get("user_id")
        user = User.get(user_id)
        if user and user.activated:
            LOG.d(f"Sending alias creation events for {user}")
            send_alias_creation_events_for_user(
                user, dispatcher=PostgresDispatcher.get()
            )
    elif job.name == JobType.SEND_EVENT_TO_WEBHOOK.value:
        send_job = SendEventToWebhookJob.create_from_job(job)
        if send_job:
            send_job.run(HttpEventSink())
    elif job.name == JobType.SYNC_SUBSCRIPTION.value:
        sync_job = SyncSubscriptionJob.create_from_job(job)
        if sync_job:
            sync_job.run(HttpEventSink())
    else:
        LOG.e("Unknown job name %s", job.name)


def get_jobs_to_run_query(taken_before_time: arrow.Arrow) -> Query:
    # Get jobs that match all conditions:
    #  - Job.state == ready OR (Job.state == taken AND Job.taken_at < now - 30 mins AND Job.attempts < 5)
    #  - Job.run_at is Null OR Job.run_at < now + 10 mins
    run_at_earliest = arrow.now().shift(minutes=+10)
    return Job.filter(
        and_(
            or_(
                Job.state == JobState.ready.value,
                and_(
                    Job.state == JobState.taken.value,
                    Job.taken_at < taken_before_time,
                    Job.attempts < config.JOB_MAX_ATTEMPTS,
                ),
            ),
            or_(Job.run_at.is_(None), and_(Job.run_at <= run_at_earliest)),
        )
    )


def get_jobs_to_run(taken_before_time: arrow.Arrow) -> List[Job]:
    query = get_jobs_to_run_query(taken_before_time)
    return (
        query.order_by(Job.priority.desc())
        .order_by(Job.run_at.asc())
        .limit(_MAX_JOBS_PER_BATCH)
        .all()
    )


def take_job(job: Job, taken_before_time: arrow.Arrow) -> bool:
    sql = """
        UPDATE job
        SET
            taken_at = :taken_time,
            attempts = attempts + 1,
            state = :taken_state
        WHERE id = :job_id
          AND (state = :ready_state OR (state=:taken_state AND taken_at < :taken_before_time))
        """
    args = {
        "taken_time": arrow.now().datetime,
        "job_id": job.id,
        "ready_state": JobState.ready.value,
        "taken_state": JobState.taken.value,
        "taken_before_time": taken_before_time.datetime,
    }
    try:
        res = Session.execute(sql, args)
        Session.commit()
    except ObjectDeletedError:
        return False

    return res.rowcount > 0


if __name__ == "__main__":
    send_version_event("job_runner")
    while True:
        # wrap in an app context to benefit from app setup like database cleanup, sentry integration, etc
        with create_light_app().app_context():
            taken_before_time = arrow.now().shift(
                minutes=-config.JOB_TAKEN_RETRY_WAIT_MINS
            )

            jobs_done = 0
            for job in get_jobs_to_run(taken_before_time):
                if not take_job(job, taken_before_time):
                    continue
                LOG.d("Take job %s", job)

                try:
                    newrelic.agent.record_custom_event("ProcessJob", {"job": job.name})
                    process_job(job)
                    job_result = "success"

                    job.state = JobState.done.value
                    jobs_done += 1
                    LOG.d("Processed job %s", job)
                except Exception as e:
                    LOG.warn(f"Error processing job (id={job.id} name={job.name}): {e}")

                    # Increment manually, as the attempts increment is done by the take_job but not
                    # updated in our instance
                    job_attempts = job.attempts + 1
                    if job_attempts >= config.JOB_MAX_ATTEMPTS:
                        LOG.warn(
                            f"Marking job (id={job.id} name={job.name} attempts={job_attempts}) as ERROR"
                        )
                        job.state = JobState.error.value
                        job_result = "error"
                    else:
                        job_result = "retry"

                newrelic.agent.record_custom_event(
                    "JobProcessed", {"job": job.name, "result": job_result}
                )
                Session.commit()

            if jobs_done == 0:
                time.sleep(10)

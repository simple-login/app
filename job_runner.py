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
)
from app.email_utils import (
    send_email,
    render,
)
from app.extensions import db
from app.import_utils import handle_batch_import
from app.log import LOG
from app.models import User, Job, BatchImport
from server import create_light_app


# fix the database connection leak issue
# use this method instead of create_app
def new_app():
    app = create_light_app()

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

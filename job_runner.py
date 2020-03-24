"""
Run scheduled jobs.
Not meant for running job at precise time (+- 1h)
"""
import time

import arrow

from app.config import JOB_ONBOARDING_1
from app.email_utils import send_email, render
from app.extensions import db
from app.log import LOG
from app.models import User, Job
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


def onboarding_1(user):
    if not user.activated:
        LOG.d("User %s is not activated", user)
        return

    if not user.notification:
        LOG.d("User %s disable notification setting", user)
        return

    send_email(
        user.email,
        f"Do you know you can send emails to anyone from your alias?",
        render("com/onboarding/send-from-alias.txt", user=user),
        render("com/onboarding/send-from-alias.html", user=user),
    )


if __name__ == "__main__":
    while True:
        # run a job 1h earlier or later is not a big deal ...
        min_dt = arrow.now().shift(hours=-1)
        max_dt = arrow.now().shift(hours=1)

        app = new_app()

        with app.app_context():
            for job in Job.query.filter(
                Job.taken == False, Job.run_at > min_dt, Job.run_at <= max_dt
            ).all():
                LOG.d("Take job %s", job)

                # mark the job as taken, whether it will be executed successfully or not
                job.taken = True
                db.session.commit()

                if job.name == JOB_ONBOARDING_1:
                    user_id = job.payload.get("user_id")
                    user = User.get(user_id)

                    # user might delete their account in the meantime
                    if user:
                        LOG.d("run onboarding_1 for user %s", user)
                        onboarding_1(user)
                else:
                    LOG.error("Unknown job name %s", job.name)

        time.sleep(10)

import arrow

from app.log import LOG
from app.models import Subscription
from server import create_app


def late_payment():
    """check for late payment
    """
    for sub in Subscription.query.all():
        if (not sub.cancelled) and sub.next_bill_date < arrow.now().date():
            LOG.error(f"user {sub.user.email} has late payment. {sub}")


if __name__ == "__main__":
    LOG.d("Start running cronjob")
    app = create_app()

    with app.app_context():
        late_payment()

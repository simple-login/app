import arrow
import stripe

from app.extensions import db
from app.log import LOG
from app.models import User, PlanEnum
from server import create_app


def downgrade_expired_plan():
    """set user plan to free when plan is expired, ie plan_expiration < now
    """
    for user in User.query.filter(
        User.plan != PlanEnum.free, User.plan_expiration < arrow.now()
    ).all():
        LOG.d("set user %s to free plan", user)

        user.plan_expiration = None
        user.plan = PlanEnum.free

        if user.stripe_customer_id:
            LOG.d("delete user %s on stripe", user.stripe_customer_id)
            stripe.Customer.delete(user.stripe_customer_id)

            user.stripe_card_token = None
            user.stripe_customer_id = None
            user.stripe_subscription_id = None

    db.session.commit()


if __name__ == "__main__":
    LOG.d("Start running cronjob")
    app = create_app()

    with app.app_context():
        downgrade_expired_plan()

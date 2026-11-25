from app import config
from app.email_utils import render
from tests.utils import create_new_user


def test_render_onboarding_pgp_html(flask_client):
    user = create_new_user()
    html = render("com/onboarding/pgp.html", user=user, to_email=user.email)
    assert f"{config.URL}/dashboard/mailbox/{user.default_mailbox_id}" in html


def test_render_trial_end_html(flask_client):
    user = create_new_user()
    html = render("transactional/trial-end.html", user=user)
    assert (
        f"In the free plan you are limited to {config.MAX_NB_EMAIL_FREE_PLAN} aliases"
        in html
    )

import os

from jinja2 import Environment, FileSystemLoader

from app.config import ROOT_DIR, URL
from app.email_utils import send_email
from app.log import LOG
from app.models import NewsletterUser


def send_newsletter_to_user(newsletter, user) -> (bool, str):
    """Return whether the newsletter is sent successfully and the error if not"""
    try:
        templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
        env = Environment(loader=FileSystemLoader(templates_dir))
        html_template = env.from_string(newsletter.html)
        text_template = env.from_string(newsletter.plain_text)

        to_email, unsubscribe_link, via_email = user.get_communication_email()
        if not to_email:
            return False, f"{user} not subscribed to newsletter"

        send_email(
            to_email,
            newsletter.subject,
            text_template.render(
                user=user,
                URL=URL,
            ),
            html_template.render(
                user=user,
                URL=URL,
            ),
        )

        NewsletterUser.create(newsletter_id=newsletter.id, user_id=user.id, commit=True)
        return True, ""
    except Exception as err:
        LOG.w(f"cannot send {newsletter} to {user}", exc_info=True)
        return False, str(err)


def send_newsletter_to_address(newsletter, user, to_address) -> (bool, str):
    """Return whether the newsletter is sent successfully and the error if not"""
    try:
        templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
        env = Environment(loader=FileSystemLoader(templates_dir))
        html_template = env.from_string(newsletter.html)
        text_template = env.from_string(newsletter.plain_text)

        send_email(
            to_address,
            newsletter.subject,
            text_template.render(
                user=user,
                URL=URL,
            ),
            html_template.render(
                user=user,
                URL=URL,
            ),
        )

        NewsletterUser.create(newsletter_id=newsletter.id, user_id=user.id, commit=True)
        return True, ""
    except Exception as err:
        LOG.w(f"cannot send {newsletter} to {user}", exc_info=True)
        return False, str(err)

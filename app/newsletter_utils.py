import os

from jinja2 import Environment, FileSystemLoader

from app.config import ROOT_DIR, URL
from app.email_utils import send_email
from app.handler.unsubscribe_encoder import UnsubscribeEncoder, UnsubscribeAction
from app.log import LOG
from app.models import NewsletterUser, Alias


def send_newsletter_to_user(newsletter, user) -> (bool, str):
    """Return whether the newsletter is sent successfully and the error if not"""
    if not user.can_send_or_receive():
        return False, f"{user} not allowed to receive newsletter"
    try:
        templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
        env = Environment(loader=FileSystemLoader(templates_dir))
        html_template = env.from_string(newsletter.html)
        text_template = env.from_string(newsletter.plain_text)

        comm_email, unsubscribe_link, via_email = user.get_communication_email()
        if not comm_email:
            return False, f"{user} not subscribed to newsletter"

        comm_alias = Alias.get_by(email=comm_email)
        comm_alias_id = -1
        if comm_alias:
            comm_alias_id = comm_alias.id

        unsubscribe_oneclick = unsubscribe_link
        if via_email and comm_alias_id > -1:
            unsubscribe_oneclick = UnsubscribeEncoder.encode(
                UnsubscribeAction.DisableAlias,
                comm_alias_id,
                force_web=True,
            ).link

        send_email(
            comm_email,
            newsletter.subject,
            text_template.render(
                user=user,
                URL=URL,
            ),
            html_template.render(
                user=user,
                URL=URL,
                unsubscribe_oneclick=unsubscribe_oneclick,
            ),
            unsubscribe_link=unsubscribe_link,
            unsubscribe_via_email=via_email,
        )

        NewsletterUser.create(newsletter_id=newsletter.id, user_id=user.id, commit=True)
        return True, ""
    except Exception as err:
        LOG.w(f"cannot send {newsletter} to {user}", exc_info=True)
        return False, str(err)


def send_newsletter_to_address(newsletter, user, to_address) -> (bool, str):
    """Return whether the newsletter is sent successfully and the error if not"""
    if not user.can_send_or_receive():
        return False, f"{user} not allowed to receive newsletter"
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

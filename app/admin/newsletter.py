from flask import flash, request
from flask_admin.actions import action
from flask_admin.form import SecureForm
from flask_login import current_user
from markupsafe import Markup

from app.admin.base import SLModelView
from app.models import User, Newsletter
from app.newsletter_utils import send_newsletter_to_user, send_newsletter_to_address


def _newsletter_plain_text_formatter(view, context, model: Newsletter, name):
    # to display newsletter plain_text with linebreaks in the list view
    return Markup(model.plain_text.replace("\n", "<br>"))


def _newsletter_html_formatter(view, context, model: Newsletter, name):
    # to display newsletter html with linebreaks in the list view
    return Markup(model.html.replace("\n", "<br>"))


class NewsletterAdmin(SLModelView):
    form_base_class = SecureForm
    list_template = "admin/model/newsletter-list.html"
    edit_template = "admin/model/newsletter-edit.html"
    edit_modal = False

    can_edit = True
    can_create = True

    column_formatters = {
        "plain_text": _newsletter_plain_text_formatter,
        "html": _newsletter_html_formatter,
    }

    @action(
        "send_newsletter_to_user",
        "Send this newsletter to myself or the specified userID",
    )
    def send_newsletter_to_user(self, newsletter_ids):
        user_id = request.form["user_id"]
        if user_id:
            user = User.get(user_id)
            if not user:
                flash(f"No such user with ID {user_id}", "error")
                return
        else:
            flash("use the current user", "info")
            user = current_user

        for newsletter_id in newsletter_ids:
            newsletter = Newsletter.get(newsletter_id)
            sent, error_msg = send_newsletter_to_user(newsletter, user)
            if sent:
                flash(f"{newsletter} sent to {user}", "success")
            else:
                flash(error_msg, "error")

    @action(
        "send_newsletter_to_address",
        "Send this newsletter to a specific address",
    )
    def send_newsletter_to_address(self, newsletter_ids):
        to_address = request.form["to_address"]
        if not to_address:
            flash("to_address missing", "error")
            return

        for newsletter_id in newsletter_ids:
            newsletter = Newsletter.get(newsletter_id)
            # use the current_user for rendering email
            sent, error_msg = send_newsletter_to_address(
                newsletter, current_user, to_address
            )
            if sent:
                flash(
                    f"{newsletter} sent to {to_address} with {current_user} context",
                    "success",
                )
            else:
                flash(error_msg, "error")

    @action(
        "clone_newsletter",
        "Clone this newsletter",
    )
    def clone_newsletter(self, newsletter_ids):
        if len(newsletter_ids) != 1:
            flash("you can only select 1 newsletter", "error")
            return

        newsletter_id = newsletter_ids[0]
        newsletter: Newsletter = Newsletter.get(newsletter_id)
        new_newsletter = Newsletter.create(
            subject=newsletter.subject,
            html=newsletter.html,
            plain_text=newsletter.plain_text,
            commit=True,
        )

        flash(f"Newsletter {new_newsletter.subject} has been cloned", "success")


class NewsletterUserAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id"]
    column_filters = ["id", "user.email", "newsletter.subject"]
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_edit = False
    can_create = False

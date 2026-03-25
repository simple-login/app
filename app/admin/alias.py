from flask import flash
from flask_admin.actions import action
from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_date_formatter
from app.db import Session
from app.models import Alias


class AliasAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.email", "email", "mailbox.email"]
    column_filters = ["id", "user.email", "email", "mailbox.email"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

    @action(
        "disable_email_spoofing_check",
        "Disable email spoofing protection",
        "Disable email spoofing protection?",
    )
    def disable_email_spoofing_check_for(self, ids):
        for alias in Alias.filter(Alias.id.in_(ids)):
            if alias.disable_email_spoofing_check:
                flash(
                    f"Email spoofing protection is already disabled on {alias.email}",
                    "warning",
                )
            else:
                alias.disable_email_spoofing_check = True
                flash(
                    f"Email spoofing protection is disabled on {alias.email}", "success"
                )

        Session.commit()

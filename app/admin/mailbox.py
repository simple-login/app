from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_date_formatter
from app.mailbox_email_match import mailboxes_matching_email
from app.models import Mailbox


class MailboxAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.email", "email"]
    column_filters = ["id", "user.email", "email"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

    def _extra_text_search_filters(self, term: str) -> list:
        # `^` (starts with) and `=` (exact) prefixes keep flask-admin's literal search
        if "@" not in term or term.startswith(("^", "=")):
            return []
        return [
            Mailbox.id.in_(mailboxes_matching_email(term).with_entities(Mailbox.id))
        ]

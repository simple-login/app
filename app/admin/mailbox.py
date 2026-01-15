from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_date_formatter


class MailboxAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.email", "email"]
    column_filters = ["id", "user.email", "email"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

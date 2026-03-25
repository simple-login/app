from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_date_formatter


class EmailLogAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id"]
    column_filters = ["id", "user.email", "mailbox.email", "contact.website_email"]

    can_edit = False
    can_create = False

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

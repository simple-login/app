from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_date_formatter


class CustomDomainAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["domain", "user.email", "user.id"]
    column_exclude_list = ["ownership_txt_token"]
    can_edit = False

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

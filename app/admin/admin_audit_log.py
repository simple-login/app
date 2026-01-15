from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_action_formatter, _admin_date_formatter


class AdminAuditLogAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["admin.id", "admin.email", "model_id", "created_at"]
    column_filters = ["admin.id", "admin.email", "model_id", "created_at"]
    column_exclude_list = ["id"]
    column_hide_backrefs = False
    can_edit = False
    can_create = False
    can_delete = False

    column_formatters = {
        "action": _admin_action_formatter,
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

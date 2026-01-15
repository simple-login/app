from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_date_formatter


class ReferralAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.email", "code", "name"]
    column_filters = ["id", "user.email", "code", "name"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

    def scaffold_list_columns(self):
        ret = super().scaffold_list_columns()
        ret.insert(0, "nb_user")
        ret.insert(0, "nb_paid_user")
        return ret

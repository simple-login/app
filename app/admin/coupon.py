from flask_admin.form import SecureForm

from app.admin.base import SLModelView, _admin_date_formatter


class CouponAdmin(SLModelView):
    form_base_class = SecureForm
    can_edit = False
    can_create = True

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

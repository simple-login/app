from flask_admin.form import SecureForm

from app.admin.base import SLModelView


class DailyMetricAdmin(SLModelView):
    form_base_class = SecureForm
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_export = True


class MetricAdmin(SLModelView):
    form_base_class = SecureForm
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_export = True

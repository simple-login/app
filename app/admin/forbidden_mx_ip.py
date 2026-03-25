from flask_admin.form import SecureForm

from app.admin.base import SLModelView


class ForbiddenMxIpAdmin(SLModelView):
    form_base_class = SecureForm
    can_create = True
    can_delete = True

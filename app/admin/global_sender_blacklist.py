from flask_admin.form import SecureForm

from app.admin.base import SLModelView


class GlobalSenderBlacklistAdmin(SLModelView):
    form_base_class = SecureForm

    can_create = True
    can_edit = True
    can_delete = True

    column_searchable_list = ("pattern", "comment")
    column_filters = ("enabled",)
    column_editable_list = ("enabled", "comment")

    # Help text for admins when adding patterns
    form_args = {
        "pattern": {
            "description": r"Regex, i.e. `@domain\.com`",
        }
    }

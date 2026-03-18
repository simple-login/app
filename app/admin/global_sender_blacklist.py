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

    # Keep the admin UI strictly on GLOBAL entries (user_id is NULL)
    column_exclude_list = ("user_id", "user")
    form_excluded_columns = ("user_id", "user")

    def get_query(self):
        return (
            super().get_query().filter(self.model.user_id.is_(None))  # type: ignore[attr-defined]
        )

    def get_count_query(self):
        return (
            super().get_count_query().filter(self.model.user_id.is_(None))  # type: ignore[attr-defined]
        )

    # Help text for admins when adding patterns
    form_args = {
        "pattern": {
            "description": r"Regex, i.e. `@domain\.com$`",
        }
    }

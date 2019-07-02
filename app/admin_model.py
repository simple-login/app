from flask import redirect, url_for, request
from flask_admin import expose, AdminIndexView
from flask_admin.contrib import sqla
from flask_login import current_user


class SLModelView(sqla.ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        return redirect(url_for("auth.login", next=request.url))


class SLAdminIndexView(AdminIndexView):
    @expose("/")
    def index(self):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login", next=request.url))

        return super(SLAdminIndexView, self).index()

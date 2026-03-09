from __future__ import annotations

import sqlalchemy
from flask import redirect, url_for, request, flash, session
from flask_admin import expose, AdminIndexView
from flask_admin.contrib import sqla
from flask_login import current_user
from markupsafe import Markup
from time import time

from app import models
from app.dashboard.views.enter_admin import _ADMIN_GAP
from app.models import AdminAuditLog, AuditLogActionEnum


def _has_valid_admin_time() -> bool:
    from app.config import ADMIN_FIDO_REQUIRED

    if ADMIN_FIDO_REQUIRED == "none":
        return True
    admin_time = session.get("admin_time")
    if not admin_time:
        return False
    if (time() - int(admin_time)) > _ADMIN_GAP:
        return False
    if ADMIN_FIDO_REQUIRED == "hardware" and not session.get("admin_hardware_auth"):
        return False
    return True


def _admin_action_formatter(view, context, model, name):
    action_name = AuditLogActionEnum.get_name(model.action)
    return "{} ({})".format(action_name, model.action)


def _admin_date_formatter(view, context, model, name):
    return model.created_at.format()


def _user_upgrade_channel_formatter(view, context, model, name):
    return Markup(model.upgrade_channel)


class SLModelView(sqla.ModelView):
    column_default_sort = ("id", True)
    column_display_pk = True
    page_size = 100

    can_edit = False
    can_create = False
    can_delete = False
    edit_modal = True

    def is_accessible(self):
        return (
            current_user.is_authenticated
            and current_user.is_admin
            and _has_valid_admin_time()
        )

    def inaccessible_callback(self, name, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("You don't have access to the admin page", "error")
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("dashboard.enter_admin", next=request.url))

    def on_model_change(self, form, model, is_created):
        changes = {}
        for attr in sqlalchemy.inspect(model).attrs:
            if attr.history.has_changes() and attr.key not in (
                "created_at",
                "updated_at",
            ):
                value = attr.value
                # If it's a model reference, get the source id
                if issubclass(type(value), models.Base):
                    value = value.id
                # otherwise, if its a generic object stringify it
                if issubclass(type(value), object):
                    value = str(value)
                changes[attr.key] = value
        auditAction = (
            AuditLogActionEnum.create_object
            if is_created
            else AuditLogActionEnum.update_object
        )
        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model=model.__class__.__name__,
            model_id=model.id,
            action=auditAction.value,
            data=changes,
        )

    def on_model_delete(self, model):
        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model=model.__class__.__name__,
            model_id=model.id,
            action=AuditLogActionEnum.delete_object.value,
            data={},
        )


class SLAdminIndexView(AdminIndexView):
    @expose("/")
    def index(self):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login", next=request.url))
        if not _has_valid_admin_time():
            return redirect(url_for("dashboard.enter_admin", next=request.url))
        return redirect(url_for("admin.email_search.index"))

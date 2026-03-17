from __future__ import annotations

from typing import Optional

import sqlalchemy
from flask import redirect, url_for, request, flash, session, Response
from flask_admin import expose, AdminIndexView, BaseView
from flask_admin.contrib import sqla
from flask_login import current_user
from markupsafe import Markup
from time import time

from app import config
from app import models
from app.models import AdminAuditLog, AuditLogActionEnum, Fido

_ADMIN_GAP = 86400


def _has_valid_admin_time() -> bool:
    if config.ADMIN_FIDO_REQUIRED == "none":
        return True
    admin_time = session.get("admin_time")
    if not admin_time:
        return False
    if (time() - int(admin_time)) > _ADMIN_GAP:
        return False
    if config.ADMIN_FIDO_REQUIRED == "hardware" and not session.get(
        "admin_hardware_auth"
    ):
        return False
    return True


def _admin_action_formatter(view, context, model, name):
    action_name = AuditLogActionEnum.get_name(model.action)
    return "{} ({})".format(action_name, model.action)


def _admin_date_formatter(view, context, model, name):
    return model.created_at.format()


def _user_upgrade_channel_formatter(view, context, model, name):
    return Markup(model.upgrade_channel)


def _redirect_if_user_is_not_allowed() -> Optional[Response]:
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("auth.login", next=request.url))
    if not _has_valid_admin_time():
        if config.ADMIN_FIDO_REQUIRED != "none":
            fido_count = Fido.filter_by(user_id=current_user.id).count()
            if fido_count == 0:
                flash(
                    "You need to register a FIDO key to access the admin panel", "error"
                )
                return redirect(url_for("dashboard.account_setting", next=request.url))
        return redirect(url_for("dashboard.enter_admin", next=request.url))


class BaseAdminView(BaseView):
    def is_accessible(self):
        return (
            current_user.is_authenticated
            and current_user.is_admin
            and _has_valid_admin_time()
        )

    def inaccessible_callback(self, name, **kwargs):
        redirect_destination = _redirect_if_user_is_not_allowed()
        return redirect_destination or redirect(url_for("dashboard.index"))


class SLModelView(sqla.ModelView, BaseAdminView):
    column_default_sort = ("id", True)
    column_display_pk = True
    page_size = 100

    can_edit = False
    can_create = False
    can_delete = False
    edit_modal = True

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
        redirect_destination = _redirect_if_user_is_not_allowed()
        return redirect_destination or redirect(url_for("admin.email_search.index"))

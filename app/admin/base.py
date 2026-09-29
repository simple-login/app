from __future__ import annotations

from typing import Optional

import sqlalchemy
from flask import redirect, url_for, request, flash, session, Response
from flask_admin import expose, AdminIndexView, BaseView
from flask_admin.contrib import sqla
from flask_admin.contrib.sqla import tools
from flask_login import current_user
from markupsafe import Markup
from sqlalchemy import Unicode, or_
from sqlalchemy.sql.expression import cast
from time import time

from app import config
from app import models
from app.models import AdminAuditLog, AuditLogActionEnum, Fido


def _has_valid_admin_time() -> bool:
    if config.ADMIN_FIDO_REQUIRED == "none":
        return True
    admin_time = session.get("admin_time")
    if not admin_time:
        return False
    if (time() - int(admin_time)) > config.ADMIN_GRACE_PERIOD:
        return False
    if config.ADMIN_FIDO_REQUIRED == "hardware" and not session.get(
        "admin_hardware_auth"
    ):
        return False
    return True


_MAX_BIGINT = 2**63 - 1


def _term_as_int(term: str) -> Optional[int]:
    """Return the term as an int if it is a plain positive integer, else None.

    flask-admin's `=` (exact match) prefix is accepted, as an exact match on a
    number is exactly what the integer lookup does.
    """
    digits = term[1:] if term.startswith("=") else term
    if not (digits.isascii() and digits.isdigit()):
        return None
    value = int(digits)
    if value > _MAX_BIGINT:
        return None
    return value


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

    def _apply_search(self, query, count_query, joins, count_joins, search):
        """Numeric-aware version of flask-admin's search.

        flask-admin casts *every* searchable column to text and matches it with
        ILIKE '%term%'. On the user list that means searching an id runs
        `CAST(users.id AS VARCHAR) ILIKE '%123%' OR CAST(users.email AS VARCHAR)
        ILIKE '%123%'`, so both the list and the count query sequentially scan
        the whole table.

        Instead, when a term is a plain integer we compare the integer columns
        directly (indexed lookup) and skip the text columns for that term; when
        it is not, we skip the integer columns, which can never match by
        equality. So a term is either an id lookup or a text search, never
        both. To search text columns for a number, use flask-admin's `^`
        (starts with) prefix.
        """
        for term in search.split(" "):
            if not term:
                continue

            term_as_int = _term_as_int(term)
            stmt = tools.parse_like_term(term)

            int_filter, int_count_filter = [], []
            text_filter, text_count_filter = [], []

            for field, path in self._search_fields:
                query, joins, alias = self._apply_path_joins(
                    query, joins, path, inner_join=False
                )

                count_alias = None
                if count_query is not None:
                    count_query, count_joins, count_alias = self._apply_path_joins(
                        count_query, count_joins, path, inner_join=False
                    )

                column = field if alias is None else getattr(alias, field.key)
                count_column = (
                    field if count_alias is None else getattr(count_alias, field.key)
                )

                # hybrid properties have no type, treat them as text
                if isinstance(getattr(field, "type", None), sqlalchemy.Integer):
                    if term_as_int is not None:
                        int_filter.append(column == term_as_int)
                        int_count_filter.append(count_column == term_as_int)
                else:
                    text_filter.append(cast(column, Unicode).ilike(stmt))
                    text_count_filter.append(cast(count_column, Unicode).ilike(stmt))

            # Prefer the integer columns, and only fall back to the text ones
            # if the term produced no integer clause. If the term produced no
            # clause at all - a non-numeric term on a view that only has
            # integer searchable columns - nothing can match, and the filter
            # must say so rather than be dropped.
            filter_stmt = int_filter or text_filter or [sqlalchemy.false()]
            count_filter_stmt = (
                int_count_filter or text_count_filter or [sqlalchemy.false()]
            )

            query = query.filter(or_(*filter_stmt))
            if count_query is not None:
                count_query = count_query.filter(or_(*count_filter_stmt))

        return query, count_query, joins, count_joins

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

from typing import List

from flask import flash
from flask_admin.actions import action
from flask_admin.form import SecureForm
from flask_login import current_user

from app.admin.base import SLModelView, _admin_date_formatter
from app.db import Session
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
from app.models import ManualSubscription, AdminAuditLog
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


class ManualSubscriptionAdmin(SLModelView):
    form_base_class = SecureForm
    can_edit = True
    column_searchable_list = ["id", "user.email"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

    @action(
        "extend_1y",
        "Extend for 1 year",
        "Extend 1 year more?",
    )
    def extend_1y(self, ids):
        self.__extend_manual_subscription(ids, msg="1 year", years=1)

    @action(
        "extend_1m",
        "Extend for 1 month",
        "Extend 1 month more?",
    )
    def extend_1m(self, ids):
        self.__extend_manual_subscription(ids, msg="1 month", months=1)

    def __extend_manual_subscription(self, ids: List[int], msg: str, **kwargs):
        for ms in ManualSubscription.filter(ManualSubscription.id.in_(ids)):
            sub: ManualSubscription = ms
            sub.end_at = sub.end_at.shift(**kwargs)
            flash(f"Extend subscription for {msg} for {sub.user}", "success")
            emit_user_audit_log(
                user=sub.user,
                action=UserAuditLogAction.Upgrade,
                message=f"Admin {current_user.email} extended manual subscription for {msg} for {sub.user}",
            )
            AdminAuditLog.extend_subscription(
                current_user.id, sub.user.id, sub.end_at, msg
            )
            EventDispatcher.send_event(
                user=sub.user,
                content=EventContent(
                    user_plan_change=UserPlanChanged(plan_end_time=sub.end_at.timestamp)
                ),
            )

        Session.commit()

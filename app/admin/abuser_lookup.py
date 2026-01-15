from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, List, Dict

from flask import redirect, url_for, request, flash
from flask_admin import BaseView, expose
from flask_login import current_user

from app.abuser_audit_log_utils import AbuserAuditLog
from app.abuser_utils import get_abuser_bundles_for_address
from app.models import User
from app.utils import sanitize_email


class AbuserLookupResult:
    def __init__(self):
        self.no_match: bool = False
        self.query: Optional[str | int] = None
        self.bundles: Optional[List[Dict]] = None
        self.audit_log: Optional[List[Dict]] = None

    @staticmethod
    def from_email_or_user_id(query: str) -> AbuserLookupResult:
        out = AbuserLookupResult()
        email: str
        audit_log: List[AbuserAuditLog] = []

        if query is None or query == "":
            out.no_match = True

            return out

        if query.isnumeric():
            user_id = int(query)
            user = User.get(user_id)

            if not user:
                out.no_match = True

                return out

            email = user.email
            audit_log = AbuserAuditLog.filter(AbuserAuditLog.user_id == user.id).all()
        else:
            email = sanitize_email(query)
            user = User.get_by(email=email)

            if user:
                audit_log = AbuserAuditLog.filter(
                    AbuserAuditLog.user_id == user.id
                ).all()

        out.query = query
        bundles = get_abuser_bundles_for_address(
            target_address=email,
            admin_id=current_user.id,
        )

        if not bundles:
            out.no_match = True

            return out

        for bundle in bundles:
            bundle_json = json.dumps(bundle)
            bundle["json"] = bundle_json

            account_id = bundle.get("account_id")
            user = User.get(int(account_id)) if account_id else None
            bundle["user"] = user

            AbuserLookupResult.convert_dt(bundle, "user_created_at")

            for mailbox_item in bundle.get("mailboxes", []):
                AbuserLookupResult.convert_dt(mailbox_item)

            for alias_item in bundle.get("aliases", []):
                AbuserLookupResult.convert_dt(alias_item)

        out.bundles = bundles
        out.audit_log = [
            {
                "admin_id": alog.admin_id,
                "action": alog.action,
                "message": alog.message,
                "created_at": alog.created_at,
            }
            for alog in audit_log
        ]

        return out

    @staticmethod
    def convert_dt(item: Dict, key: str = "created_at"):
        raw_date = item.get(key, "")

        if raw_date:
            item[key] = datetime.fromisoformat(raw_date)


class AbuserLookupAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        query: Optional[str] = request.args.get("search")

        if query is None:
            result = AbuserLookupResult()
        else:
            result = AbuserLookupResult.from_email_or_user_id(query)

        return self.render(
            "admin/abuser_lookup.html",
            data=result,
            query=query,
        )

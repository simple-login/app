from typing import Optional

from flask import redirect, url_for, request, flash, Response
from flask_admin import expose
from flask_admin.form import SecureForm
from flask_admin.model.template import EndpointLinkRowAction
from flask_login import current_user
from markupsafe import Markup

from app import s3
from app.admin.base import SLModelView, _admin_date_formatter
from app.db import Session
from app.models import (
    AdminAuditLog,
    ProviderComplaintState,
    Phase,
    ProviderComplaint,
)


def _transactionalcomplaint_state_formatter(view, context, model, name):
    return "{} ({})".format(ProviderComplaintState(model.state).name, model.state)


def _transactionalcomplaint_phase_formatter(view, context, model, name):
    return Phase(model.phase).name


def _transactionalcomplaint_refused_email_id_formatter(view, context, model, name):
    markupstring = "<a href='{}'>{}</a>".format(
        url_for(".download_eml", id=model.id), model.refused_email.full_report_path
    )
    return Markup(markupstring)


class ProviderComplaintAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.id", "created_at"]
    column_filters = ["user.id", "state"]
    column_hide_backrefs = False
    can_edit = False
    can_create = False
    can_delete = False

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
        "state": _transactionalcomplaint_state_formatter,
        "phase": _transactionalcomplaint_phase_formatter,
        "refused_email": _transactionalcomplaint_refused_email_id_formatter,
    }

    column_extra_row_actions = [  # Add a new action button
        EndpointLinkRowAction("fa fa-check-square", ".mark_ok"),
    ]

    def _get_complaint(self) -> Optional[ProviderComplaint]:
        complain_id = request.args.get("id")
        if complain_id is None:
            flash("Missing id", "error")
            return None
        complaint = ProviderComplaint.get_by(id=complain_id)
        if not complaint:
            flash("Could not find complaint", "error")
            return None
        return complaint

    @expose("/mark_ok", methods=["GET"])
    def mark_ok(self):
        complaint = self._get_complaint()
        if not complaint:
            return redirect("/admin/transactionalcomplaint/")
        complaint.state = ProviderComplaintState.reviewed.value
        Session.commit()
        return redirect("/admin/transactionalcomplaint/")

    @expose("/download_eml", methods=["GET"])
    def download_eml(self):
        complaint = self._get_complaint()
        if not complaint:
            return redirect("/admin/transactionalcomplaint/")
        eml_path = complaint.refused_email.full_report_path
        eml_data = s3.download_email(eml_path)
        AdminAuditLog.downloaded_provider_complaint(current_user.id, complaint.id)
        Session.commit()
        return Response(
            eml_data,
            mimetype="message/rfc822",
            headers={
                "Content-Disposition": "attachment;filename={}".format(
                    complaint.refused_email.path
                )
            },
        )

import arrow
from flask import flash, redirect, url_for, request, render_template
from flask_login import login_required, current_user
from flask_wtf import FlaskForm

from app.constants import JobType
from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.log import LOG
from app.models import Subscription, Job
from app.user_audit_log_utils import (
    emit_user_marked_for_deletion_audit_log,
    USER_REQUESTED_DELETION_REASON,
)


class DeleteDirForm(FlaskForm):
    pass


@dashboard_bp.route("/delete_account", methods=["GET", "POST"])
@login_required
@sudo_required
def delete_account():
    delete_form = DeleteDirForm()
    if request.method == "POST" and request.form.get("form-name") == "delete-account":
        if not delete_form.validate():
            flash("Invalid request", "warning")
            return render_template(
                "dashboard/delete_account.html", delete_form=delete_form
            )
        sub: Subscription = current_user.get_paddle_subscription()
        # user who has canceled can also re-subscribe
        if sub and not sub.cancelled:
            flash("Please cancel your current subscription first", "warning")
            return redirect(url_for("dashboard.setting"))

        # Schedule delete account job
        LOG.w("schedule delete account job for %s", current_user)
        source = "webapp"
        emit_user_marked_for_deletion_audit_log(
            user=current_user, source=source, reason=USER_REQUESTED_DELETION_REASON
        )
        Job.create(
            name=JobType.DELETE_ACCOUNT.value,
            payload={
                "user_id": current_user.id,
                "source": source,
                "reason": USER_REQUESTED_DELETION_REASON,
            },
            run_at=arrow.now(),
            commit=True,
        )

        flash(
            "Your account deletion has been scheduled. "
            "You'll receive an email when the deletion is finished",
            "info",
        )
        return redirect(url_for("dashboard.setting"))

    return render_template("dashboard/delete_account.html", delete_form=delete_form)

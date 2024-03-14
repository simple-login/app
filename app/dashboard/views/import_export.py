from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.extensions import limiter
from app.jobs.export_user_data_job import ExportUserDataJob
from app.utils import (
    CSRFValidationForm,
)


@dashboard_bp.route("/import_export", methods=["GET", "POST"])
@login_required
@sudo_required
@limiter.limit("5/minute", methods=["POST"])
def import_export():
    csrf_form = CSRFValidationForm()

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(url_for("dashboard.setting"))
        if request.form.get("form-name") == "send-full-user-report":
            if ExportUserDataJob(current_user).store_job_in_db():
                flash(
                    "You will receive your SimpleLogin data via email shortly",
                    "success",
                )
            else:
                flash("An export of your data is currently in progress", "error")

    return render_template(
        "dashboard/import_export.html",
        csrf_form=csrf_form,
    )

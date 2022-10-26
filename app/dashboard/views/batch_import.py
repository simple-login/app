import arrow
from flask import render_template, flash, request, redirect, url_for
from flask_login import login_required, current_user

from app import s3
from app.config import JOB_BATCH_IMPORT
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.models import File, BatchImport, Job
from app.utils import random_string, CSRFValidationForm


@dashboard_bp.route("/batch_import", methods=["GET", "POST"])
@login_required
def batch_import_route():
    # only for users who have custom domains
    if not current_user.verified_custom_domains():
        flash("Alias batch import is only available for custom domains", "warning")

    if current_user.disable_import:
        flash(
            "you cannot use the import feature, please contact SimpleLogin team",
            "error",
        )
        return redirect(url_for("dashboard.index"))

    batch_imports = BatchImport.filter_by(
        user_id=current_user.id, processed=False
    ).all()

    csrf_form = CSRFValidationForm()

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            redirect(request.url)
        if len(batch_imports) > 10:
            flash(
                "You have too many imports already. Wait until some get cleaned up",
                "error",
            )
            return render_template(
                "dashboard/batch_import.html",
                batch_imports=batch_imports,
                csrf_form=csrf_form,
            )

        alias_file = request.files["alias-file"]

        file_path = random_string(20) + ".csv"
        file = File.create(user_id=current_user.id, path=file_path)
        s3.upload_from_bytesio(file_path, alias_file)
        Session.flush()
        LOG.d("upload file %s to s3 at %s", file, file_path)

        bi = BatchImport.create(user_id=current_user.id, file_id=file.id)
        Session.flush()
        LOG.d("Add a batch import job %s for %s", bi, current_user)

        # Schedule batch import job
        Job.create(
            name=JOB_BATCH_IMPORT,
            payload={"batch_import_id": bi.id},
            run_at=arrow.now(),
        )
        Session.commit()

        flash(
            "The file has been uploaded successfully and the import will start shortly",
            "success",
        )

        return redirect(url_for("dashboard.batch_import_route"))

    return render_template(
        "dashboard/batch_import.html", batch_imports=batch_imports, csrf_form=csrf_form
    )

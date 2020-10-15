import arrow
from flask import render_template, flash, request, redirect, url_for
from flask_login import login_required, current_user

from app import s3
from app.config import JOB_BATCH_IMPORT
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import File, BatchImport, Job
from app.utils import random_string


@dashboard_bp.route("/batch_import", methods=["GET", "POST"])
@login_required
def batch_import_route():
    # only for users who have custom domains
    if not current_user.verified_custom_domains():
        flash("Alias batch import is only available for custom domains", "warning")

    batch_imports = BatchImport.query.filter_by(user_id=current_user.id).all()

    if request.method == "POST":
        alias_file = request.files["alias-file"]

        file_path = random_string(20) + ".csv"
        file = File.create(user_id=current_user.id, path=file_path)
        s3.upload_from_bytesio(file_path, alias_file)
        db.session.flush()
        LOG.d("upload file %s to s3 at %s", file, file_path)

        bi = BatchImport.create(user_id=current_user.id, file_id=file.id)
        db.session.flush()
        LOG.debug("Add a batch import job %s for %s", bi, current_user)

        # Schedule batch import job
        Job.create(
            name=JOB_BATCH_IMPORT,
            payload={"batch_import_id": bi.id},
            run_at=arrow.now(),
        )
        db.session.commit()

        flash(
            "The file has been uploaded successfully and the import will start shortly",
            "success",
        )

        return redirect(url_for("dashboard.batch_import_route"))

    return render_template("dashboard/batch_import.html", batch_imports=batch_imports)

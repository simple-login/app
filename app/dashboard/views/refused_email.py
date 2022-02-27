from flask import render_template, request
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.log import LOG
from app.models import EmailLog


@dashboard_bp.route("/refused_email", methods=["GET", "POST"])
@login_required
def refused_email_route():
    # Highlight a refused email
    highlight_id = request.args.get("highlight_id")
    if highlight_id:
        try:
            highlight_id = int(highlight_id)
        except ValueError:
            LOG.w("Cannot parse highlight_id %s", highlight_id)
            highlight_id = None

    email_logs: [EmailLog] = (
        EmailLog.filter(
            EmailLog.user_id == current_user.id, EmailLog.refused_email_id.isnot(None)
        )
        .order_by(EmailLog.id.desc())
        .all()
    )

    # make sure the highlighted email_log is the first email_log
    highlight_index = None
    for ix, email_log in enumerate(email_logs):
        if email_log.id == highlight_id:
            highlight_index = ix
            break

    if highlight_index:
        email_logs.insert(0, email_logs.pop(highlight_index))

    return render_template("dashboard/refused_email.html", **locals())

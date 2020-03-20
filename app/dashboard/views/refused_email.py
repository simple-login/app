from flask import render_template, request
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.models import EmailLog


@dashboard_bp.route("/refused_email", methods=["GET", "POST"])
@login_required
def refused_email_route():
    # Highlight a refused email
    highlight_fel_id = request.args.get("highlight_fel_id")
    if highlight_fel_id:
        highlight_fel_id = int(highlight_fel_id)

    fels: [EmailLog] = EmailLog.query.filter(
        EmailLog.user_id == current_user.id, EmailLog.refused_email_id != None
    ).all()

    # make sure the highlighted fel is the first fel
    highlight_index = None
    for ix, fel in enumerate(fels):
        if fel.id == highlight_fel_id:
            highlight_index = ix
            break

    if highlight_index:
        fels.insert(0, fels.pop(highlight_index))

    return render_template("dashboard/refused_email.html", **locals())

from app.dashboard.base import dashboard_bp
from flask_login import login_required, current_user
from app.alias_utils import alias_export_csv


@dashboard_bp.route("/alias_export", methods=["GET"])
@login_required
def alias_export_route():
    return alias_export_csv(current_user)

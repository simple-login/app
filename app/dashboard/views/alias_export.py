from app.dashboard.base import dashboard_bp
from flask_login import login_required, current_user
from app.alias_utils import alias_export_csv
from app.dashboard.views.enter_sudo import sudo_required
from app.extensions import limiter


@dashboard_bp.route("/alias_export", methods=["GET"])
@login_required
@sudo_required
@limiter.limit("2/minute")
def alias_export_route():
    return alias_export_csv(current_user)

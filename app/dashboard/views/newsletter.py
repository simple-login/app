from app.dashboard.base import dashboard_bp


@dashboard_bp.route("/", methods=["GET", "POST"])
def notification_setting():
    pass

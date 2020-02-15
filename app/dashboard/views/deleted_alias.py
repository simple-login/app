from flask import render_template
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.models import DeletedAlias


@dashboard_bp.route("/deleted_alias", methods=["GET", "POST"])
@login_required
def deleted_alias_route():
    deleted_aliases = DeletedAlias.query.filter_by(user_id=current_user.id)

    return render_template("dashboard/deleted_alias.html", **locals())

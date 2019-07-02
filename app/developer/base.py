from flask import Blueprint, render_template
from flask_login import current_user

from app.log import LOG

developer_bp = Blueprint(
    name="developer",
    import_name=__name__,
    url_prefix="/developer",
    template_folder="templates",
)


@developer_bp.before_request
def before_request():
    if current_user.is_authenticated and not current_user.is_developer:
        LOG.error("User %s tries to go developer tab")
        return render_template("error/403.html"), 403

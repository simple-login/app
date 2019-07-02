from flask import Blueprint

dashboard_bp = Blueprint(
    name="dashboard",
    import_name=__name__,
    url_prefix="/dashboard",
    template_folder="templates",
)

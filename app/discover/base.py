from flask import Blueprint

discover_bp = Blueprint(
    name="discover",
    import_name=__name__,
    url_prefix="/discover",
    template_folder="templates",
)

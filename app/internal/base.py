from flask import Blueprint

internal_bp = Blueprint(
    name="internal",
    import_name=__name__,
    url_prefix="/internal",
    template_folder="templates",
)

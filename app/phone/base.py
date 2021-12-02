from flask import Blueprint

phone_bp = Blueprint(
    name="phone",
    import_name=__name__,
    url_prefix="/phone",
    template_folder="templates",
)

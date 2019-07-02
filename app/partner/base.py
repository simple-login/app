from flask import Blueprint

partner_bp = Blueprint(
    name="partner",
    import_name=__name__,
    url_prefix="/partner",
    template_folder="templates",
)

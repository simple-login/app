from flask import Blueprint

onboarding_bp = Blueprint(
    name="onboarding",
    import_name=__name__,
    url_prefix="/onboarding",
    template_folder="templates",
)

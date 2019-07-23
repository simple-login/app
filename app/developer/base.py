from flask import Blueprint

developer_bp = Blueprint(
    name="developer",
    import_name=__name__,
    url_prefix="/developer",
    template_folder="templates",
)

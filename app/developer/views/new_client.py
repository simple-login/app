from flask import redirect, url_for, flash
from flask_login import login_required

from app.developer.base import developer_bp


@developer_bp.route("/new_client", methods=["GET", "POST"])
@login_required
def new_client():
    # Creating new "Sign in with SimpleLogin" clients is no longer allowed.
    # The route is kept so that old links and bookmarks land on a clear notice.
    flash(
        "It is no longer possible to create new websites for Sign in with SimpleLogin. "
        "Your existing websites keep working as usual.",
        "warning",
    )
    return redirect(url_for("developer.index"))

from flask import redirect, url_for, flash

from app.internal.base import internal_bp
from app.session import clear_session_sudo_mode


@internal_bp.route("/exit-sudo-mode")
def exit_sudo_mode():
    clear_session_sudo_mode()
    flash("Exited sudo mode", "info")
    return redirect(url_for("dashboard.index"))

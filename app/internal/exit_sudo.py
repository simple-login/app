from flask import session, redirect, url_for, flash

from app.internal.base import internal_bp


@internal_bp.route("/exit-sudo-mode")
def exit_sudo_mode():
    session["sudo_time"] = 0
    flash("Exited sudo mode", "info")
    return redirect(url_for("dashboard.index"))

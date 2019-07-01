from flask import render_template
from flask_login import logout_user

from app.auth.base import auth_bp


@auth_bp.route("/logout")
def logout():
    logout_user()
    return render_template("auth/logout.html")

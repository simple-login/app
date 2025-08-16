from flask import flash, redirect, url_for, request, render_template
from flask_login import login_required, current_user
from flask_wtf import FlaskForm

from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.models import Subscription
from app.user_utils import soft_delete_user


class DeleteDirForm(FlaskForm):
    pass


@dashboard_bp.route("/delete_account", methods=["GET", "POST"])
@login_required
@sudo_required
def delete_account():
    delete_form = DeleteDirForm()
    if request.method == "POST" and request.form.get("form-name") == "delete-account":
        if not delete_form.validate():
            flash("Invalid request", "warning")
            return render_template(
                "dashboard/delete_account.html", delete_form=delete_form
            )
        sub: Subscription = current_user.get_paddle_subscription()
        # user who has canceled can also re-subscribe
        if sub and not sub.cancelled:
            flash("Please cancel your current subscription first", "warning")
            return redirect(url_for("dashboard.setting"))

        soft_delete_user(current_user, "webapp")
        flash("Your account deletion has been scheduled", "info")
        return redirect(url_for("dashboard.setting"))

    return render_template("dashboard/delete_account.html", delete_form=delete_form)

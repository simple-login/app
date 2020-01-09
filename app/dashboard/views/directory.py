from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.config import EMAIL_DOMAIN
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.models import Directory


class NewDirForm(FlaskForm):
    name = StringField(
        "name", validators=[validators.DataRequired(), validators.Length(min=3)]
    )


@dashboard_bp.route("/directory", methods=["GET", "POST"])
@login_required
def directory():
    # only premium user can add directory
    if not current_user.is_premium():
        flash("Only premium user can add directories", "warning")
        return redirect(url_for("dashboard.index"))

    dirs = Directory.query.filter_by(user_id=current_user.id).all()

    new_dir_form = NewDirForm()

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            dir_id = request.form.get("dir-id")
            dir = Directory.get(dir_id)

            if not dir:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.directory"))
            elif dir.user_id != current_user.id:
                flash("You cannot delete this directory", "warning")
                return redirect(url_for("dashboard.directory"))

            name = dir.name
            Directory.delete(dir_id)
            db.session.commit()
            flash(f"Directory {name} has been deleted", "success")

            return redirect(url_for("dashboard.directory"))

        elif request.form.get("form-name") == "create":
            if new_dir_form.validate():
                new_dir_name = new_dir_form.name.data.lower()

                if Directory.get_by(name=new_dir_name):
                    flash(f"{new_dir_name} already added", "warning")
                else:
                    new_dir = Directory.create(
                        name=new_dir_name, user_id=current_user.id
                    )
                    db.session.commit()

                    flash(f"Directory {new_dir.name} is created", "success")

                    return redirect(url_for("dashboard.directory",))

    return render_template(
        "dashboard/directory.html",
        dirs=dirs,
        new_dir_form=new_dir_form,
        EMAIL_DOMAIN=EMAIL_DOMAIN,
    )

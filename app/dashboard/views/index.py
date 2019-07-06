from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app import email_utils
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, ClientUser


@dashboard_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    # User generates a new email
    if request.method == "POST":
        if request.form.get("form-name") == "trigger-email":
            gen_email_id = request.form.get("gen-email-id")
            gen_email = GenEmail.get(gen_email_id)

            LOG.d("trigger an email to %s", gen_email)
            email_utils.send(
                gen_email.email,
                "A Test Email",
                f"""
Hi {current_user.name}! <br><br>
This is a test to make sure that you receive emails sent from SimpleLogin. <br><br>
If you have any questions, feel free to reply to this email :). <br><br>
Have a nice day! <br><br>
SimpleLogin team.
            """,
            )
            flash(
                f"An email sent to {gen_email.email} is on its way, please check your inbox/spam folder",
                "success",
            )

        elif request.form.get("form-name") == "create-random-email":
            can_create_new_email = current_user.can_create_new_email()

            if can_create_new_email:
                gen_email = GenEmail.create_new_gen_email(user_id=current_user.id)
                db.session.commit()

                LOG.d("generate new email %s for user %s", gen_email, current_user)
                flash(f"Email {gen_email.email} has been created", "success")
            else:
                flash(f"You need to upgrade your plan to create new email.", "warning")

        elif request.form.get("form-name") == "switch-email-forwarding":
            gen_email_id = request.form.get("gen-email-id")
            gen_email: GenEmail = GenEmail.get(gen_email_id)

            LOG.d("switch email forwarding for %s", gen_email)

            gen_email.enabled = not gen_email.enabled
            if gen_email.enabled:
                flash(
                    f"The email forwarding for {gen_email.email} has been enabled",
                    "success",
                )
            else:
                flash(
                    f"The email forwarding for {gen_email.email} has been disabled",
                    "warning",
                )
            db.session.commit()

        elif request.form.get("form-name") == "delete-email":
            gen_email_id = request.form.get("gen-email-id")
            gen_email: GenEmail = GenEmail.get(gen_email_id)

            LOG.d("delete gen email %s", gen_email)
            email = gen_email.email
            GenEmail.delete(gen_email.id)
            db.session.commit()
            flash(f"Email alias {email} has been deleted", "success")

        return redirect(url_for("dashboard.index"))

    client_users = (
        ClientUser.filter_by(user_id=current_user.id)
        .options(joinedload(ClientUser.client))
        .options(joinedload(ClientUser.gen_email))
        .all()
    )

    sorted(client_users, key=lambda cu: cu.client.name)

    gen_emails = (
        GenEmail.filter_by(user_id=current_user.id)
        .order_by(GenEmail.email)
        .options(joinedload(GenEmail.client_users))
        .all()
    )

    return render_template(
        "dashboard/index.html", client_users=client_users, gen_emails=gen_emails
    )

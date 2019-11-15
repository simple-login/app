from flask import render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import email_utils
from app.developer.base import developer_bp
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import Client


class NewClientForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])


@developer_bp.route("/new_client", methods=["GET", "POST"])
@login_required
def new_client():
    form = NewClientForm()

    if form.validate_on_submit():
        client = Client.create_new(form.name.data, current_user.id)
        db.session.commit()

        notify_admin(
            f"user {current_user} created new app {client.name}",
            html_content=f"""
name: {current_user.name} <br>
email: {current_user.email} <br>
app: {client.name}
""",
        )

        flash("Your app has been created", "success")

        # if this is the first app user creates, sends an email to ask for feedback
        if db.session.query(Client).filter_by(user_id=current_user.id).count() == 1:
            LOG.d(f"send feedback email to user {current_user}")
            email_utils.send_by_sendgrid(
                current_user.email,
                "SimpleLogin questions/feedbacks",
                f"""
Hi {current_user.name}! <br><br>

This is Son, SimpleLogin CEO & Founder :) <br><br>

Even though I lead the company, I’m the "product person" and the user experience you get from our product means a lot to me. <br><br>

Our users and developers love SimpleLogin and its simplicity (hence the "simple" in the name 😉), but if there's anything that's bugging you, even the smallest of issues that could be done better, I want to hear about it - so hit the reply button.
<br><br>

And ok, this is an automated email, but if you reply it comes directly to me and will be answered by me.
<br><br>

Best regards, <br>
Son. <br>
<br>
----------------------------------<br>
Son NK <br>
SimpleLogin founder. <br>
https://simplelogin.io <br>
https://twitter.com/nguyenkims <br>
                             """,
                plain_content="""
                             Hi there!

This is Son, SimpleLogin CEO & Founder :).

Even though I lead the company, I’m the "product person" and the user experience you get from our product means a lot to me.

Our users and developers love SimpleLogin and its simplicity (hence the "simple" in the name 😉), but if there's anything that's bugging you, even the smallest of issues that could be done better, I want to hear about it - so hit the reply button.

And ok, this is an automated email, but if you reply it comes directly to me and will be answered by me.

Best regards,
Son.
""",
            )

        return redirect(
            url_for("developer.client_detail", client_id=client.id, is_new=1)
        )

    return render_template("developer/new_client.html", form=form)

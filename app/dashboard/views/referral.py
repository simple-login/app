from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import EmailLog, Referral
from app.utils import random_string


@dashboard_bp.route("/referral", methods=["GET", "POST"])
@login_required
def referral_route():
    if request.method == "POST":
        # Generate a new unique ref code
        code = random_string(15)
        for _ in range(100):
            if not Referral.get_by(code=code):
                # found
                break

            LOG.warning("Referral Code %s already used", code)
            code = random_string(15)

        referral = Referral.create(user_id=current_user.id, code=code)
        db.session.commit()
        flash("A new referral code has been created", "success")
        return redirect(url_for("dashboard.referral_route", highlight_id=referral.id))

    # Highlight a referral
    highlight_id = request.args.get("highlight_id")
    if highlight_id:
        highlight_id = int(highlight_id)

    referrals = Referral.query.filter_by(user_id=current_user.id).all()
    # make sure the highlighted referral is the first referral
    highlight_index = None
    for ix, referral in enumerate(referrals):
        if referral.id == highlight_id:
            highlight_index = ix
            break

    if highlight_index:
        referrals.insert(0, referrals.pop(highlight_index))

    return render_template("dashboard/referral.html", **locals())

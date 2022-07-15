import arrow
from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app.db import Session
from app.models import PhoneReservation, User
from app.phone.base import phone_bp

current_user: User


@phone_bp.route("/reservation/<int:reservation_id>", methods=["GET", "POST"])
@login_required
def reservation_route(reservation_id: int):
    reservation: PhoneReservation = PhoneReservation.get(reservation_id)
    if not reservation or reservation.user_id != current_user.id:
        flash("Unknown error, redirect back to phone page", "warning")
        return redirect(url_for("phone.index"))

    phone_number = reservation.number

    if request.method == "POST":
        if request.form.get("form-name") == "release":
            time_left = reservation.end - arrow.now()
            if time_left.seconds > 0:
                current_user.phone_quota += time_left.seconds // 60
                flash(
                    f"Your phone quota is increased by {time_left.seconds // 60} minutes",
                    "success",
                )
            reservation.end = arrow.now()
            Session.commit()

            flash(f"{phone_number.number} is released", "success")
            return redirect(url_for("phone.index"))

    return render_template(
        "phone/phone_reservation.html",
        phone_number=phone_number,
        reservation=reservation,
        now=arrow.now(),
    )

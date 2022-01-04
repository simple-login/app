from typing import Dict

import arrow
from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func

from app.db import Session
from app.models import PhoneCountry, PhoneNumber, PhoneReservation
from app.phone.base import phone_bp


@phone_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if not current_user.can_use_phone:
        flash("You can't use this page", "error")
        return redirect(url_for("dashboard.index"))

    countries = available_countries()

    now = arrow.now()
    reservations = PhoneReservation.filter(
        PhoneReservation.user_id == current_user.id,
        PhoneReservation.start < now,
        PhoneReservation.end > now,
    ).all()

    past_reservations = PhoneReservation.filter(
        PhoneReservation.user_id == current_user.id,
        PhoneReservation.end <= now,
    ).all()

    if request.method == "POST":
        try:
            nb_minute = int(request.form.get("minute"))
        except ValueError:
            flash("Number of minutes must be specified", "error")
            return redirect(request.url)

        if current_user.phone_quota < nb_minute:
            flash(
                f"You don't have enough phone quota. Current quota is {current_user.phone_quota}",
                "error",
            )
            return redirect(request.url)

        country_id = request.form.get("country")
        country = PhoneCountry.get(country_id)

        # get the first phone number available
        now = arrow.now()
        busy_phone_number_subquery = (
            Session.query(PhoneReservation.number_id)
            .filter(PhoneReservation.start < now, PhoneReservation.end > now)
            .subquery()
        )

        phone_number = (
            Session.query(PhoneNumber)
            .filter(
                PhoneNumber.country_id == country.id,
                PhoneNumber.id.notin_(busy_phone_number_subquery),
                PhoneNumber.active,
            )
            .first()
        )

        if phone_number:
            phone_reservation = PhoneReservation.create(
                number_id=phone_number.id,
                start=arrow.now(),
                end=arrow.now().shift(minutes=nb_minute),
                user_id=current_user.id,
            )

            current_user.phone_quota -= nb_minute
            Session.commit()

            return redirect(
                url_for("phone.reservation_route", reservation_id=phone_reservation.id)
            )
        else:
            flash(
                f"No phone number available for {country.name} during {nb_minute} minutes"
            )

    return render_template(
        "phone/index.html",
        countries=countries,
        reservations=reservations,
        past_reservations=past_reservations,
    )


def available_countries() -> [PhoneCountry]:
    now = arrow.now()

    phone_count_by_countries: Dict[PhoneCountry, int] = dict()
    for country, count in (
        Session.query(PhoneCountry, func.count(PhoneNumber.id))
        .join(PhoneNumber, PhoneNumber.country_id == PhoneCountry.id)
        .filter(PhoneNumber.active.is_(True))
        .group_by(PhoneCountry)
        .all()
    ):
        phone_count_by_countries[country] = count

    busy_phone_count_by_countries: Dict[PhoneCountry, int] = dict()
    for country, count in (
        Session.query(PhoneCountry, func.count(PhoneNumber.id))
        .join(PhoneNumber, PhoneNumber.country_id == PhoneCountry.id)
        .join(PhoneReservation, PhoneReservation.number_id == PhoneNumber.id)
        .filter(PhoneReservation.start < now, PhoneReservation.end > now)
        .group_by(PhoneCountry)
        .all()
    ):
        busy_phone_count_by_countries[country] = count

    ret = []
    for country in phone_count_by_countries:
        if (
            country not in busy_phone_count_by_countries
            or phone_count_by_countries[country]
            > busy_phone_count_by_countries[country]
        ):
            ret.append(country)

    return ret


def available_numbers() -> [PhoneNumber]:
    Session.query(PhoneReservation).filter(PhoneReservation.start)

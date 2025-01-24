from flask import url_for

from app.models import Coupon, LifetimeCoupon
from app.utils import random_string
from tests.utils import login


def test_redeem_coupon_without_subscription(flask_client):
    user = login(flask_client)
    code = random_string(10)
    Coupon.create(code=code, nb_year=1, commit=True)

    r = flask_client.post(
        url_for("dashboard.coupon_route"),
        data={"code": code},
    )

    assert r.status_code == 200
    coupon = Coupon.get_by(code=code)
    assert coupon.used
    assert coupon.used_by_user_id == user.id


def test_redeem_lifetime_coupon(flask_client):
    login(flask_client)
    code = random_string(10)
    LifetimeCoupon.create(code=code, nb_used=1, commit=True)

    r = flask_client.post(
        url_for("dashboard.lifetime_licence"),
        data={"code": code},
    )

    assert r.status_code == 302
    coupon = LifetimeCoupon.get_by(code=code)
    assert coupon.nb_used == 0

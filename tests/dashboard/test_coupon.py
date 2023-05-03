from flask import url_for
from app.models import Coupon
from app.utils import random_string
from tests.utils import login


def test_use_coupon(flask_client):
    user = login(flask_client)
    code = random_string(10)
    Coupon.create(code=code, nb_year=1, commit=True)

    r = flask_client.post(
        url_for("dashboard.coupon_route"),
        data={"code": code},
    )

    assert r.status_code == 302
    coupon = Coupon.get_by(code=code)
    assert coupon.used
    assert coupon.used_by_user_id == user.id

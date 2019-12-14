from app.paddle_utils import verify_incoming_request


def test_verify_incoming_request():
    # the request comes from Paddle simulation
    request_data = {
        "alert_id": "1647146853",
        "alert_name": "payment_succeeded",
        "balance_currency": "EUR",
        "balance_earnings": "966.81",
        "balance_fee": "16.03",
        "balance_gross": "107.37",
        "balance_tax": "670.85",
        "checkout_id": "8-a367127c071e8a2-cba0a50da3",
        "country": "AU",
        "coupon": "Coupon 7",
        "currency": "USD",
        "customer_name": "customer_name",
        "earnings": "820.91",
        "email": "awyman@example.org",
        "event_time": "2019-12-14 18:43:09",
        "fee": "0.26",
        "ip": "65.220.94.158",
        "marketing_consent": "1",
        "order_id": "8",
        "passthrough": "Example String",
        "payment_method": "paypal",
        "payment_tax": "0.18",
        "product_id": "3",
        "product_name": "Example String",
        "quantity": "29",
        "receipt_url": "https://my.paddle.com/receipt/4/5854e29100fd226-440fa7ba7a",
        "sale_gross": "568.82",
        "used_price_override": "true",
        "p_signature": "CQrBWKnAuhBOWdgu6+upbgpLo38c2oQJVgNHLTNsQoaUHtJgHUXzfUfQdcnD9q3EWZuQtyFXXPkygxx/fMbcu+UTnfxkjyecoHio8w4T858jU4VOy1RPqYy6fqazG1vlngiuYqEdgo8OHT/6oIJAf+NWm1v1iwbpr62rDygzJWZrqTzVSKkESfW8/4goxlN2BWr6eaN/4nKQ4gaHq5ee3/7vMmkrLAQG509x9SK3H0bYvh3pvbWMUhYNz8j+7GZRlXcSCpMKw1nkO/jK4IXKW0rtSwgyVjJhpX+/rt2byaCmWEvP0LtGhrug9xAqMYJ3tDCJmwSk2cXG8rPE7oeBwEEElZrQJdbV+i6Tw5rw9LaqEGrjhSkOapfpINdct5UpKXybIyiRZZ111yhJL081T1rtBqb8L+wsPnHG8GzI1Fg5je98j5aXGQU9hcw5nQN779IJQWNN+GbDQZ+Eleu5c6ZYauxpKzE8s/Vs2a4/70KB6WBK6NKxNSIIoOTumKqnfEiPN0pxZp5MMi2dRW7wu7VqvcLbIEYtCkOLnjxVyko32B6AMIgn8CuHvQp9ScPdNdU6B8dBXhdVfV75iYSwx+ythun5d3f357IecaZep27QQmKR/b7/pv4iMOiHKmFQRz9EKwqQm/3Xg2WS4GA4t1X0nslXMuEeRnX6xTaxbvk=",
    }
    assert verify_incoming_request(request_data)

    # add a new field in request_data -> verify should fail
    request_data["new_field"] = "new_field"
    assert not verify_incoming_request(request_data)

    # modify existing field -> verify should fail
    request_data["sale_gross"] = "1.23"
    assert not verify_incoming_request(request_data)

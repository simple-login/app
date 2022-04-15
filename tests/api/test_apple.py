from flask import url_for

from tests.api.utils import get_new_user_and_api_key


def test_apple_process_payment(flask_client):
    user, api_key = get_new_user_and_api_key()

    receipt_data = """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"""

    r = flask_client.post(
        url_for("api.apple_process_payment"),
        headers={"Authentication": api_key.code},
        json={"receipt_data": receipt_data},
    )

    # will fail anyway as there's apple secret is not valid
    assert r.status_code == 400
    assert r.json == {"error": "Processing failed"}


def test_apple_update_notification(flask_client):
    user, api_key = get_new_user_and_api_key()

    payload = {
        "unified_receipt": {
            "latest_receipt": "long string",
            "pending_renewal_info": [
                {
                    "is_in_billing_retry_period": "0",
                    "auto_renew_status": "0",
                    "original_transaction_id": "1000000654277043",
                    "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                    "expiration_intent": "1",
                    "auto_renew_product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                }
            ],
            "environment": "Sandbox",
            "status": 0,
            "latest_receipt_info": [
                {
                    "expires_date_pst": "2020-04-20 21:11:57 America/Los_Angeles",
                    "purchase_date": "2020-04-21 03:11:57 Etc/GMT",
                    "purchase_date_ms": "1587438717000",
                    "original_purchase_date_ms": "1587420715000",
                    "transaction_id": "1000000654329911",
                    "original_transaction_id": "1000000654277043",
                    "quantity": "1",
                    "expires_date_ms": "1587442317000",
                    "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
                    "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                    "subscription_group_identifier": "20624274",
                    "web_order_line_item_id": "1000000051891577",
                    "expires_date": "2020-04-21 04:11:57 Etc/GMT",
                    "is_in_intro_offer_period": "false",
                    "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
                    "purchase_date_pst": "2020-04-20 20:11:57 America/Los_Angeles",
                    "is_trial_period": "false",
                },
                {
                    "expires_date_pst": "2020-04-20 20:11:57 America/Los_Angeles",
                    "purchase_date": "2020-04-21 02:11:57 Etc/GMT",
                    "purchase_date_ms": "1587435117000",
                    "original_purchase_date_ms": "1587420715000",
                    "transaction_id": "1000000654313889",
                    "original_transaction_id": "1000000654277043",
                    "quantity": "1",
                    "expires_date_ms": "1587438717000",
                    "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
                    "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                    "subscription_group_identifier": "20624274",
                    "web_order_line_item_id": "1000000051890729",
                    "expires_date": "2020-04-21 03:11:57 Etc/GMT",
                    "is_in_intro_offer_period": "false",
                    "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
                    "purchase_date_pst": "2020-04-20 19:11:57 America/Los_Angeles",
                    "is_trial_period": "false",
                },
                {
                    "expires_date_pst": "2020-04-20 19:11:54 America/Los_Angeles",
                    "purchase_date": "2020-04-21 01:11:54 Etc/GMT",
                    "purchase_date_ms": "1587431514000",
                    "original_purchase_date_ms": "1587420715000",
                    "transaction_id": "1000000654300800",
                    "original_transaction_id": "1000000654277043",
                    "quantity": "1",
                    "expires_date_ms": "1587435114000",
                    "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
                    "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                    "subscription_group_identifier": "20624274",
                    "web_order_line_item_id": "1000000051890161",
                    "expires_date": "2020-04-21 02:11:54 Etc/GMT",
                    "is_in_intro_offer_period": "false",
                    "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
                    "purchase_date_pst": "2020-04-20 18:11:54 America/Los_Angeles",
                    "is_trial_period": "false",
                },
                {
                    "expires_date_pst": "2020-04-20 18:11:54 America/Los_Angeles",
                    "purchase_date": "2020-04-21 00:11:54 Etc/GMT",
                    "purchase_date_ms": "1587427914000",
                    "original_purchase_date_ms": "1587420715000",
                    "transaction_id": "1000000654293615",
                    "original_transaction_id": "1000000654277043",
                    "quantity": "1",
                    "expires_date_ms": "1587431514000",
                    "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
                    "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                    "subscription_group_identifier": "20624274",
                    "web_order_line_item_id": "1000000051889539",
                    "expires_date": "2020-04-21 01:11:54 Etc/GMT",
                    "is_in_intro_offer_period": "false",
                    "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
                    "purchase_date_pst": "2020-04-20 17:11:54 America/Los_Angeles",
                    "is_trial_period": "false",
                },
                {
                    "expires_date_pst": "2020-04-20 17:11:54 America/Los_Angeles",
                    "purchase_date": "2020-04-20 23:11:54 Etc/GMT",
                    "purchase_date_ms": "1587424314000",
                    "original_purchase_date_ms": "1587420715000",
                    "transaction_id": "1000000654285464",
                    "original_transaction_id": "1000000654277043",
                    "quantity": "1",
                    "expires_date_ms": "1587427914000",
                    "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
                    "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                    "subscription_group_identifier": "20624274",
                    "web_order_line_item_id": "1000000051888827",
                    "expires_date": "2020-04-21 00:11:54 Etc/GMT",
                    "is_in_intro_offer_period": "false",
                    "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
                    "purchase_date_pst": "2020-04-20 16:11:54 America/Los_Angeles",
                    "is_trial_period": "false",
                },
                {
                    "expires_date_pst": "2020-04-20 16:11:54 America/Los_Angeles",
                    "purchase_date": "2020-04-20 22:11:54 Etc/GMT",
                    "purchase_date_ms": "1587420714000",
                    "original_purchase_date_ms": "1587420715000",
                    "transaction_id": "1000000654277043",
                    "original_transaction_id": "1000000654277043",
                    "quantity": "1",
                    "expires_date_ms": "1587424314000",
                    "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
                    "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
                    "subscription_group_identifier": "20624274",
                    "web_order_line_item_id": "1000000051888825",
                    "expires_date": "2020-04-20 23:11:54 Etc/GMT",
                    "is_in_intro_offer_period": "false",
                    "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
                    "purchase_date_pst": "2020-04-20 15:11:54 America/Los_Angeles",
                    "is_trial_period": "false",
                },
            ],
        },
        "auto_renew_status_change_date": "2020-04-21 04:11:33 Etc/GMT",
        "environment": "Sandbox",
        "auto_renew_status": "false",
        "auto_renew_status_change_date_pst": "2020-04-20 21:11:33 America/Los_Angeles",
        "latest_expired_receipt": "long string",
        "latest_expired_receipt_info": {
            "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
            "quantity": "1",
            "subscription_group_identifier": "20624274",
            "unique_vendor_identifier": "4C4DF6BA-DE2A-4737-9A68-5992338886DC",
            "original_purchase_date_ms": "1587420715000",
            "expires_date_formatted": "2020-04-21 04:11:57 Etc/GMT",
            "is_in_intro_offer_period": "false",
            "purchase_date_ms": "1587438717000",
            "expires_date_formatted_pst": "2020-04-20 21:11:57 America/Los_Angeles",
            "is_trial_period": "false",
            "item_id": "1508744966",
            "unique_identifier": "b55fc3dcc688e979115af0697a0195be78be7cbd",
            "original_transaction_id": "1000000654277043",
            "expires_date": "1587442317000",
            "transaction_id": "1000000654329911",
            "bvrs": "3",
            "web_order_line_item_id": "1000000051891577",
            "version_external_identifier": "834289833",
            "bid": "io.simplelogin.ios-app",
            "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
            "purchase_date": "2020-04-21 03:11:57 Etc/GMT",
            "purchase_date_pst": "2020-04-20 20:11:57 America/Los_Angeles",
            "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
        },
        "password": "22b9d5a110dd4344a1681631f1f95f55",
        "auto_renew_status_change_date_ms": "1587442293000",
        "auto_renew_product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
        "notification_type": "DID_CHANGE_RENEWAL_STATUS",
    }

    r = flask_client.post(
        url_for("api.apple_update_notification"),
        headers={"Authentication": api_key.code},
        json=payload,
    )

    # will fail anyway as there's no such AppleSub in Test DB
    assert r.status_code == 400
    assert r.json == {"error": "Processing failed"}

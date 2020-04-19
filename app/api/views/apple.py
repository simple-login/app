from typing import Optional

import arrow
import requests
from flask import g
from flask import jsonify
from flask import request
from flask_cors import cross_origin

from app.api.base import api_bp, verify_api_key
from app.config import APPLE_API_SECRET
from app.log import LOG
from app.models import PlanEnum, AppleSubscription

_MONTHLY_PRODUCT_ID = "io.simplelogin.ios_app.subscription.premium.monthly"
_YEARLY_PRODUCT_ID = "io.simplelogin.ios_app.subscription.premium.yearly"

# Apple API URL
_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"
_PROD_URL = "https://buy.itunes.apple.com/verifyReceipt"


@api_bp.route("/apple/process_payment", methods=["POST"])
@cross_origin()
@verify_api_key
def apple_process_payment():
    """
    Process payment
    Input:
        receipt_data: in body
    Output:
        200 of the payment is successful, i.e. user is upgraded to premium

    """
    user = g.user
    receipt_data = request.get_json().get("receipt_data")

    apple_sub = verify_receipt(receipt_data, user)
    if apple_sub:
        return jsonify(ok=True), 200

    return jsonify(ok=False), 400


@api_bp.route("/apple/update_notification", methods=["GET", "POST"])
def apple_update_notification():
    """
    The "Subscription Status URL" to receive update notifications from Apple
    TODO: to implement
    """
    LOG.d("request data %s", request.data)
    LOG.d("request json %s", request.get_json(silent=True))
    LOG.d("request %s", request)

    return jsonify(ignored=True), 400


def verify_receipt(receipt_data, user) -> Optional[AppleSubscription]:
    """Call verifyReceipt endpoint and create/update AppleSubscription table
    Call the production URL for verifyReceipt first,
    and proceed to verify with the sandbox URL if receive a 21007 status code.

    Return AppleSubscription object if success

    https://developer.apple.com/documentation/appstorereceipts/verifyreceipt
    """
    r = requests.post(
        _PROD_URL, json={"receipt-data": receipt_data, "password": APPLE_API_SECRET}
    )

    if r.json() == {"status": 21007}:
        # try sandbox_url
        LOG.warning("Use the sandbox url instead")
        r = requests.post(
            _SANDBOX_URL,
            json={"receipt-data": receipt_data, "password": APPLE_API_SECRET},
        )

    data = r.json()
    LOG.d("response from Apple %s", data)
    # data has the following format
    # {
    #     "status": 0,
    #     "environment": "Sandbox",
    #     "receipt": {
    #         "receipt_type": "ProductionSandbox",
    #         "adam_id": 0,
    #         "app_item_id": 0,
    #         "bundle_id": "io.simplelogin.ios-app",
    #         "application_version": "2",
    #         "download_id": 0,
    #         "version_external_identifier": 0,
    #         "receipt_creation_date": "2020-04-18 16:36:34 Etc/GMT",
    #         "receipt_creation_date_ms": "1587227794000",
    #         "receipt_creation_date_pst": "2020-04-18 09:36:34 America/Los_Angeles",
    #         "request_date": "2020-04-18 16:46:36 Etc/GMT",
    #         "request_date_ms": "1587228396496",
    #         "request_date_pst": "2020-04-18 09:46:36 America/Los_Angeles",
    #         "original_purchase_date": "2013-08-01 07:00:00 Etc/GMT",
    #         "original_purchase_date_ms": "1375340400000",
    #         "original_purchase_date_pst": "2013-08-01 00:00:00 America/Los_Angeles",
    #         "original_application_version": "1.0",
    #         "in_app": [
    #             {
    #                 "quantity": "1",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #                 "transaction_id": "1000000653584474",
    #                 "original_transaction_id": "1000000653584474",
    #                 "purchase_date": "2020-04-18 16:27:42 Etc/GMT",
    #                 "purchase_date_ms": "1587227262000",
    #                 "purchase_date_pst": "2020-04-18 09:27:42 America/Los_Angeles",
    #                 "original_purchase_date": "2020-04-18 16:27:44 Etc/GMT",
    #                 "original_purchase_date_ms": "1587227264000",
    #                 "original_purchase_date_pst": "2020-04-18 09:27:44 America/Los_Angeles",
    #                 "expires_date": "2020-04-18 16:32:42 Etc/GMT",
    #                 "expires_date_ms": "1587227562000",
    #                 "expires_date_pst": "2020-04-18 09:32:42 America/Los_Angeles",
    #                 "web_order_line_item_id": "1000000051847459",
    #                 "is_trial_period": "false",
    #                 "is_in_intro_offer_period": "false",
    #             },
    #             {
    #                 "quantity": "1",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #                 "transaction_id": "1000000653584861",
    #                 "original_transaction_id": "1000000653584474",
    #                 "purchase_date": "2020-04-18 16:32:42 Etc/GMT",
    #                 "purchase_date_ms": "1587227562000",
    #                 "purchase_date_pst": "2020-04-18 09:32:42 America/Los_Angeles",
    #                 "original_purchase_date": "2020-04-18 16:27:44 Etc/GMT",
    #                 "original_purchase_date_ms": "1587227264000",
    #                 "original_purchase_date_pst": "2020-04-18 09:27:44 America/Los_Angeles",
    #                 "expires_date": "2020-04-18 16:37:42 Etc/GMT",
    #                 "expires_date_ms": "1587227862000",
    #                 "expires_date_pst": "2020-04-18 09:37:42 America/Los_Angeles",
    #                 "web_order_line_item_id": "1000000051847461",
    #                 "is_trial_period": "false",
    #                 "is_in_intro_offer_period": "false",
    #             },
    #         ],
    #     },
    #     "latest_receipt_info": [
    #         {
    #             "quantity": "1",
    #             "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #             "transaction_id": "1000000653584474",
    #             "original_transaction_id": "1000000653584474",
    #             "purchase_date": "2020-04-18 16:27:42 Etc/GMT",
    #             "purchase_date_ms": "1587227262000",
    #             "purchase_date_pst": "2020-04-18 09:27:42 America/Los_Angeles",
    #             "original_purchase_date": "2020-04-18 16:27:44 Etc/GMT",
    #             "original_purchase_date_ms": "1587227264000",
    #             "original_purchase_date_pst": "2020-04-18 09:27:44 America/Los_Angeles",
    #             "expires_date": "2020-04-18 16:32:42 Etc/GMT",
    #             "expires_date_ms": "1587227562000",
    #             "expires_date_pst": "2020-04-18 09:32:42 America/Los_Angeles",
    #             "web_order_line_item_id": "1000000051847459",
    #             "is_trial_period": "false",
    #             "is_in_intro_offer_period": "false",
    #             "subscription_group_identifier": "20624274",
    #         },
    #         {
    #             "quantity": "1",
    #             "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #             "transaction_id": "1000000653584861",
    #             "original_transaction_id": "1000000653584474",
    #             "purchase_date": "2020-04-18 16:32:42 Etc/GMT",
    #             "purchase_date_ms": "1587227562000",
    #             "purchase_date_pst": "2020-04-18 09:32:42 America/Los_Angeles",
    #             "original_purchase_date": "2020-04-18 16:27:44 Etc/GMT",
    #             "original_purchase_date_ms": "1587227264000",
    #             "original_purchase_date_pst": "2020-04-18 09:27:44 America/Los_Angeles",
    #             "expires_date": "2020-04-18 16:37:42 Etc/GMT",
    #             "expires_date_ms": "1587227862000",
    #             "expires_date_pst": "2020-04-18 09:37:42 America/Los_Angeles",
    #             "web_order_line_item_id": "1000000051847461",
    #             "is_trial_period": "false",
    #             "is_in_intro_offer_period": "false",
    #             "subscription_group_identifier": "20624274",
    #         },
    #         {
    #             "quantity": "1",
    #             "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #             "transaction_id": "1000000653585235",
    #             "original_transaction_id": "1000000653584474",
    #             "purchase_date": "2020-04-18 16:38:16 Etc/GMT",
    #             "purchase_date_ms": "1587227896000",
    #             "purchase_date_pst": "2020-04-18 09:38:16 America/Los_Angeles",
    #             "original_purchase_date": "2020-04-18 16:27:44 Etc/GMT",
    #             "original_purchase_date_ms": "1587227264000",
    #             "original_purchase_date_pst": "2020-04-18 09:27:44 America/Los_Angeles",
    #             "expires_date": "2020-04-18 16:43:16 Etc/GMT",
    #             "expires_date_ms": "1587228196000",
    #             "expires_date_pst": "2020-04-18 09:43:16 America/Los_Angeles",
    #             "web_order_line_item_id": "1000000051847500",
    #             "is_trial_period": "false",
    #             "is_in_intro_offer_period": "false",
    #             "subscription_group_identifier": "20624274",
    #         },
    #         {
    #             "quantity": "1",
    #             "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #             "transaction_id": "1000000653585760",
    #             "original_transaction_id": "1000000653584474",
    #             "purchase_date": "2020-04-18 16:44:25 Etc/GMT",
    #             "purchase_date_ms": "1587228265000",
    #             "purchase_date_pst": "2020-04-18 09:44:25 America/Los_Angeles",
    #             "original_purchase_date": "2020-04-18 16:27:44 Etc/GMT",
    #             "original_purchase_date_ms": "1587227264000",
    #             "original_purchase_date_pst": "2020-04-18 09:27:44 America/Los_Angeles",
    #             "expires_date": "2020-04-18 16:49:25 Etc/GMT",
    #             "expires_date_ms": "1587228565000",
    #             "expires_date_pst": "2020-04-18 09:49:25 America/Los_Angeles",
    #             "web_order_line_item_id": "1000000051847566",
    #             "is_trial_period": "false",
    #             "is_in_intro_offer_period": "false",
    #             "subscription_group_identifier": "20624274",
    #         },
    #     ],
    #     "latest_receipt": "very long string",
    #     "pending_renewal_info": [
    #         {
    #             "auto_renew_product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #             "original_transaction_id": "1000000653584474",
    #             "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #             "auto_renew_status": "1",
    #         }
    #     ],
    # }

    if data["status"] != 0:
        LOG.error(
            "verifyReceipt status !=0, probably invalid receipt. User %s", user,
        )
        return None

    # each item in data["receipt"]["in_app"] has the following format
    # {
    #     "quantity": "1",
    #     "product_id": "io.simplelogin.ios_app.subscription.premium.monthly",
    #     "transaction_id": "1000000653584474",
    #     "original_transaction_id": "1000000653584474",
    #     "purchase_date": "2020-04-18 16:27:42 Etc/GMT",
    #     "purchase_date_ms": "1587227262000",
    #     "purchase_date_pst": "2020-04-18 09:27:42 America/Los_Angeles",
    #     "original_purchase_date": "2020-04-18 16:27:44 Etc/GMT",
    #     "original_purchase_date_ms": "1587227264000",
    #     "original_purchase_date_pst": "2020-04-18 09:27:44 America/Los_Angeles",
    #     "expires_date": "2020-04-18 16:32:42 Etc/GMT",
    #     "expires_date_ms": "1587227562000",
    #     "expires_date_pst": "2020-04-18 09:32:42 America/Los_Angeles",
    #     "web_order_line_item_id": "1000000051847459",
    #     "is_trial_period": "false",
    #     "is_in_intro_offer_period": "false",
    # }
    transactions = data["receipt"]["in_app"]
    latest_transaction = max(transactions, key=lambda t: int(t["expires_date_ms"]))
    original_transaction_id = latest_transaction["original_transaction_id"]
    expires_date = arrow.get(int(latest_transaction["expires_date_ms"]) / 1000)
    plan = (
        PlanEnum.monthly
        if latest_transaction["product_id"] == _MONTHLY_PRODUCT_ID
        else PlanEnum.yearly
    )

    apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=user.id)

    if apple_sub:
        LOG.d(
            "Create new AppleSubscription for user %s, expired at %s, plan %s",
            user,
            expires_date,
            plan,
        )
        apple_sub.receipt_data = receipt_data
        apple_sub.expires_date = expires_date
        apple_sub.original_transaction_id = original_transaction_id
        apple_sub.plan = plan
    else:
        LOG.d(
            "Create new AppleSubscription for user %s, expired at %s, plan %s",
            user,
            expires_date,
            plan,
        )
        apple_sub = AppleSubscription.create(
            user_id=user.id,
            receipt_data=receipt_data,
            expires_date=expires_date,
            original_transaction_id=original_transaction_id,
            plan=plan,
        )

    return apple_sub

from typing import Optional

import arrow
import requests
from flask import g
from flask import jsonify
from flask import request
from requests import RequestException

from app.api.base import api_bp, require_api_auth
from app.config import APPLE_API_SECRET, MACAPP_APPLE_API_SECRET
from app.db import Session
from app.log import LOG
from app.models import PlanEnum, AppleSubscription

_MONTHLY_PRODUCT_ID = "io.simplelogin.ios_app.subscription.premium.monthly"
_YEARLY_PRODUCT_ID = "io.simplelogin.ios_app.subscription.premium.yearly"

_MACAPP_MONTHLY_PRODUCT_ID = "io.simplelogin.macapp.subscription.premium.monthly"
_MACAPP_YEARLY_PRODUCT_ID = "io.simplelogin.macapp.subscription.premium.yearly"

# Apple API URL
_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"
_PROD_URL = "https://buy.itunes.apple.com/verifyReceipt"


@api_bp.route("/apple/process_payment", methods=["POST"])
@require_api_auth
def apple_process_payment():
    """
    Process payment
    Input:
        receipt_data: in body
        (optional) is_macapp: in body
    Output:
        200 of the payment is successful, i.e. user is upgraded to premium

    """
    user = g.user
    LOG.d("request for /apple/process_payment from %s", user)
    data = request.get_json()
    receipt_data = data.get("receipt_data")
    is_macapp = "is_macapp" in data

    if is_macapp:
        password = MACAPP_APPLE_API_SECRET
    else:
        password = APPLE_API_SECRET

    apple_sub = verify_receipt(receipt_data, user, password)
    if apple_sub:
        return jsonify(ok=True), 200

    return jsonify(error="Processing failed"), 400


@api_bp.route("/apple/update_notification", methods=["GET", "POST"])
def apple_update_notification():
    """
    The "Subscription Status URL" to receive update notifications from Apple
    """
    # request.json looks like this
    # will use unified_receipt.latest_receipt_info and NOT latest_expired_receipt_info
    # more info on https://developer.apple.com/documentation/appstoreservernotifications/responsebody
    # {
    #     "unified_receipt": {
    #         "latest_receipt": "long string",
    #         "pending_renewal_info": [
    #             {
    #                 "is_in_billing_retry_period": "0",
    #                 "auto_renew_status": "0",
    #                 "original_transaction_id": "1000000654277043",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #                 "expiration_intent": "1",
    #                 "auto_renew_product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #             }
    #         ],
    #         "environment": "Sandbox",
    #         "status": 0,
    #         "latest_receipt_info": [
    #             {
    #                 "expires_date_pst": "2020-04-20 21:11:57 America/Los_Angeles",
    #                 "purchase_date": "2020-04-21 03:11:57 Etc/GMT",
    #                 "purchase_date_ms": "1587438717000",
    #                 "original_purchase_date_ms": "1587420715000",
    #                 "transaction_id": "1000000654329911",
    #                 "original_transaction_id": "1000000654277043",
    #                 "quantity": "1",
    #                 "expires_date_ms": "1587442317000",
    #                 "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #                 "subscription_group_identifier": "20624274",
    #                 "web_order_line_item_id": "1000000051891577",
    #                 "expires_date": "2020-04-21 04:11:57 Etc/GMT",
    #                 "is_in_intro_offer_period": "false",
    #                 "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
    #                 "purchase_date_pst": "2020-04-20 20:11:57 America/Los_Angeles",
    #                 "is_trial_period": "false",
    #             },
    #             {
    #                 "expires_date_pst": "2020-04-20 20:11:57 America/Los_Angeles",
    #                 "purchase_date": "2020-04-21 02:11:57 Etc/GMT",
    #                 "purchase_date_ms": "1587435117000",
    #                 "original_purchase_date_ms": "1587420715000",
    #                 "transaction_id": "1000000654313889",
    #                 "original_transaction_id": "1000000654277043",
    #                 "quantity": "1",
    #                 "expires_date_ms": "1587438717000",
    #                 "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #                 "subscription_group_identifier": "20624274",
    #                 "web_order_line_item_id": "1000000051890729",
    #                 "expires_date": "2020-04-21 03:11:57 Etc/GMT",
    #                 "is_in_intro_offer_period": "false",
    #                 "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
    #                 "purchase_date_pst": "2020-04-20 19:11:57 America/Los_Angeles",
    #                 "is_trial_period": "false",
    #             },
    #             {
    #                 "expires_date_pst": "2020-04-20 19:11:54 America/Los_Angeles",
    #                 "purchase_date": "2020-04-21 01:11:54 Etc/GMT",
    #                 "purchase_date_ms": "1587431514000",
    #                 "original_purchase_date_ms": "1587420715000",
    #                 "transaction_id": "1000000654300800",
    #                 "original_transaction_id": "1000000654277043",
    #                 "quantity": "1",
    #                 "expires_date_ms": "1587435114000",
    #                 "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #                 "subscription_group_identifier": "20624274",
    #                 "web_order_line_item_id": "1000000051890161",
    #                 "expires_date": "2020-04-21 02:11:54 Etc/GMT",
    #                 "is_in_intro_offer_period": "false",
    #                 "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
    #                 "purchase_date_pst": "2020-04-20 18:11:54 America/Los_Angeles",
    #                 "is_trial_period": "false",
    #             },
    #             {
    #                 "expires_date_pst": "2020-04-20 18:11:54 America/Los_Angeles",
    #                 "purchase_date": "2020-04-21 00:11:54 Etc/GMT",
    #                 "purchase_date_ms": "1587427914000",
    #                 "original_purchase_date_ms": "1587420715000",
    #                 "transaction_id": "1000000654293615",
    #                 "original_transaction_id": "1000000654277043",
    #                 "quantity": "1",
    #                 "expires_date_ms": "1587431514000",
    #                 "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #                 "subscription_group_identifier": "20624274",
    #                 "web_order_line_item_id": "1000000051889539",
    #                 "expires_date": "2020-04-21 01:11:54 Etc/GMT",
    #                 "is_in_intro_offer_period": "false",
    #                 "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
    #                 "purchase_date_pst": "2020-04-20 17:11:54 America/Los_Angeles",
    #                 "is_trial_period": "false",
    #             },
    #             {
    #                 "expires_date_pst": "2020-04-20 17:11:54 America/Los_Angeles",
    #                 "purchase_date": "2020-04-20 23:11:54 Etc/GMT",
    #                 "purchase_date_ms": "1587424314000",
    #                 "original_purchase_date_ms": "1587420715000",
    #                 "transaction_id": "1000000654285464",
    #                 "original_transaction_id": "1000000654277043",
    #                 "quantity": "1",
    #                 "expires_date_ms": "1587427914000",
    #                 "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #                 "subscription_group_identifier": "20624274",
    #                 "web_order_line_item_id": "1000000051888827",
    #                 "expires_date": "2020-04-21 00:11:54 Etc/GMT",
    #                 "is_in_intro_offer_period": "false",
    #                 "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
    #                 "purchase_date_pst": "2020-04-20 16:11:54 America/Los_Angeles",
    #                 "is_trial_period": "false",
    #             },
    #             {
    #                 "expires_date_pst": "2020-04-20 16:11:54 America/Los_Angeles",
    #                 "purchase_date": "2020-04-20 22:11:54 Etc/GMT",
    #                 "purchase_date_ms": "1587420714000",
    #                 "original_purchase_date_ms": "1587420715000",
    #                 "transaction_id": "1000000654277043",
    #                 "original_transaction_id": "1000000654277043",
    #                 "quantity": "1",
    #                 "expires_date_ms": "1587424314000",
    #                 "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
    #                 "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #                 "subscription_group_identifier": "20624274",
    #                 "web_order_line_item_id": "1000000051888825",
    #                 "expires_date": "2020-04-20 23:11:54 Etc/GMT",
    #                 "is_in_intro_offer_period": "false",
    #                 "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
    #                 "purchase_date_pst": "2020-04-20 15:11:54 America/Los_Angeles",
    #                 "is_trial_period": "false",
    #             },
    #         ],
    #     },
    #     "auto_renew_status_change_date": "2020-04-21 04:11:33 Etc/GMT",
    #     "environment": "Sandbox",
    #     "auto_renew_status": "false",
    #     "auto_renew_status_change_date_pst": "2020-04-20 21:11:33 America/Los_Angeles",
    #     "latest_expired_receipt": "long string",
    #     "latest_expired_receipt_info": {
    #         "original_purchase_date_pst": "2020-04-20 15:11:55 America/Los_Angeles",
    #         "quantity": "1",
    #         "subscription_group_identifier": "20624274",
    #         "unique_vendor_identifier": "4C4DF6BA-DE2A-4737-9A68-5992338886DC",
    #         "original_purchase_date_ms": "1587420715000",
    #         "expires_date_formatted": "2020-04-21 04:11:57 Etc/GMT",
    #         "is_in_intro_offer_period": "false",
    #         "purchase_date_ms": "1587438717000",
    #         "expires_date_formatted_pst": "2020-04-20 21:11:57 America/Los_Angeles",
    #         "is_trial_period": "false",
    #         "item_id": "1508744966",
    #         "unique_identifier": "b55fc3dcc688e979115af0697a0195be78be7cbd",
    #         "original_transaction_id": "1000000654277043",
    #         "expires_date": "1587442317000",
    #         "transaction_id": "1000000654329911",
    #         "bvrs": "3",
    #         "web_order_line_item_id": "1000000051891577",
    #         "version_external_identifier": "834289833",
    #         "bid": "io.simplelogin.ios-app",
    #         "product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #         "purchase_date": "2020-04-21 03:11:57 Etc/GMT",
    #         "purchase_date_pst": "2020-04-20 20:11:57 America/Los_Angeles",
    #         "original_purchase_date": "2020-04-20 22:11:55 Etc/GMT",
    #     },
    #     "password": "22b9d5a110dd4344a1681631f1f95f55",
    #     "auto_renew_status_change_date_ms": "1587442293000",
    #     "auto_renew_product_id": "io.simplelogin.ios_app.subscription.premium.yearly",
    #     "notification_type": "DID_CHANGE_RENEWAL_STATUS",
    # }
    LOG.d("request for /api/apple/update_notification")
    data = request.get_json()
    if not (
        data
        and data.get("unified_receipt")
        and data["unified_receipt"].get("latest_receipt_info")
    ):
        LOG.d("Invalid data %s", data)
        return jsonify(error="Empty Response"), 400

    transactions = data["unified_receipt"]["latest_receipt_info"]

    # dict of original_transaction_id and transaction
    latest_transactions = {}

    for transaction in transactions:
        original_transaction_id = transaction["original_transaction_id"]
        if not latest_transactions.get(original_transaction_id):
            latest_transactions[original_transaction_id] = transaction

        if (
            transaction["expires_date_ms"]
            > latest_transactions[original_transaction_id]["expires_date_ms"]
        ):
            latest_transactions[original_transaction_id] = transaction

    for original_transaction_id, transaction in latest_transactions.items():
        expires_date = arrow.get(int(transaction["expires_date_ms"]) / 1000)
        plan = (
            PlanEnum.monthly
            if transaction["product_id"]
            in (_MONTHLY_PRODUCT_ID, _MACAPP_MONTHLY_PRODUCT_ID)
            else PlanEnum.yearly
        )

        apple_sub: AppleSubscription = AppleSubscription.get_by(
            original_transaction_id=original_transaction_id
        )

        if apple_sub:
            user = apple_sub.user
            LOG.d(
                "Update AppleSubscription for user %s, expired at %s, plan %s",
                user,
                expires_date,
                plan,
            )
            apple_sub.receipt_data = data["unified_receipt"]["latest_receipt"]
            apple_sub.expires_date = expires_date
            apple_sub.plan = plan
            apple_sub.product_id = transaction["product_id"]
            Session.commit()
            return jsonify(ok=True), 200
        else:
            LOG.w(
                "No existing AppleSub for original_transaction_id %s",
                original_transaction_id,
            )
            LOG.d("request data %s", data)
            return jsonify(error="Processing failed"), 400


def verify_receipt(receipt_data, user, password) -> Optional[AppleSubscription]:
    """
    Call https://buy.itunes.apple.com/verifyReceipt and create/update AppleSubscription table
    Call the production URL for verifyReceipt first,
        use sandbox URL if receive a 21007 status code.

    Return AppleSubscription object if success

    https://developer.apple.com/documentation/appstorereceipts/verifyreceipt
    """
    LOG.d("start verify_receipt")
    try:
        r = requests.post(
            _PROD_URL, json={"receipt-data": receipt_data, "password": password}
        )
    except RequestException:
        LOG.w("cannot call Apple server %s", _PROD_URL)
        return None

    if r.status_code >= 500:
        LOG.w("Apple server error, response:%s %s", r, r.content)
        return None

    if r.json() == {"status": 21007}:
        # try sandbox_url
        LOG.w("Use the sandbox url instead")
        r = requests.post(
            _SANDBOX_URL,
            json={"receipt-data": receipt_data, "password": password},
        )

    data = r.json()
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
        LOG.e(
            "verifyReceipt status !=0, probably invalid receipt. User %s, data %s",
            user,
            data,
        )
        return None

    # use responseBody.Latest_receipt_info and not responseBody.Receipt.In_app
    # as recommended on https://developer.apple.com/documentation/appstorereceipts/responsebody/receipt/in_app
    # each item in data["latest_receipt_info"] has the following format
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
    transactions = data.get("latest_receipt_info")
    if not transactions:
        LOG.i("Empty transactions in data %s", data)
        return None

    latest_transaction = max(transactions, key=lambda t: int(t["expires_date_ms"]))
    original_transaction_id = latest_transaction["original_transaction_id"]
    expires_date = arrow.get(int(latest_transaction["expires_date_ms"]) / 1000)
    plan = (
        PlanEnum.monthly
        if latest_transaction["product_id"]
        in (_MONTHLY_PRODUCT_ID, _MACAPP_MONTHLY_PRODUCT_ID)
        else PlanEnum.yearly
    )

    apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=user.id)

    if apple_sub:
        LOG.d(
            "Update AppleSubscription for user %s, expired at %s (%s), plan %s",
            user,
            expires_date,
            expires_date.humanize(),
            plan,
        )
        apple_sub.receipt_data = receipt_data
        apple_sub.expires_date = expires_date
        apple_sub.original_transaction_id = original_transaction_id
        apple_sub.product_id = latest_transaction["product_id"]
        apple_sub.plan = plan
    else:
        # the same original_transaction_id has been used on another account
        if AppleSubscription.get_by(original_transaction_id=original_transaction_id):
            LOG.e("Same Apple Sub has been used before, current user %s", user)
            return None

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
            product_id=latest_transaction["product_id"],
        )

    Session.commit()

    return apple_sub

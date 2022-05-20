from app.onboarding.base import onboarding_bp
from enum import Enum
from flask import redirect, render_template, request, url_for


CHROME_EXTENSION_LINK = "https://chrome.google.com/webstore/detail/simpleloginreceive-send-e/dphilobhebphkdjbpfohgikllaljmgbn"
FIREFOX_EXTENSION_LINK = "https://addons.mozilla.org/firefox/addon/simplelogin/"


class Browser(Enum):
    Firefox = 1
    Chrome = 2
    Other = 3


def get_browser() -> Browser:
    user_agent = request.user_agent
    if user_agent.browser in ["chrome", "edge", "opera", "webkit"]:
        return Browser.Chrome
    elif user_agent.browser in ["mozilla", "firefox"]:
        return Browser.Firefox
    return Browser.Other


def is_mobile() -> bool:
    return request.user_agent.platform in [
        "android",
        "blackberry",
        "ipad",
        "iphone",
        "symbian",
    ]


@onboarding_bp.route("/account_activated", methods=["GET"])
def account_activated():
    if is_mobile():
        return redirect(url_for("dashboard.index"))

    browser = get_browser()
    if browser == Browser.Chrome:
        extension_link = CHROME_EXTENSION_LINK
        browser_name = "Chrome"
    elif browser == Browser.Firefox:
        extension_link = FIREFOX_EXTENSION_LINK
        browser_name = "Firefox"
    else:
        return redirect(url_for("dashboard.index"))

    return render_template(
        "onboarding/account_activated.html",
        extension_link=extension_link,
        browser_name=browser_name,
    )

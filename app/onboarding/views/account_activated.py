from app.onboarding.base import onboarding_bp
from enum import Enum
from flask import redirect, render_template, request, url_for
from flask_login import login_required


CHROME_EXTENSION_LINK = "https://chrome.google.com/webstore/detail/simpleloginreceive-send-e/dphilobhebphkdjbpfohgikllaljmgbn"
FIREFOX_EXTENSION_LINK = "https://addons.mozilla.org/firefox/addon/simplelogin/"
EDGE_EXTENSION_LINK = "https://microsoftedge.microsoft.com/addons/detail/simpleloginreceive-sen/diacfpipniklenphgljfkmhinphjlfff"


class Browser(Enum):
    Firefox = 1
    Chrome = 2
    Edge = 3
    Other = 4


def is_mobile() -> bool:
    return request.user_agent.platform in [
        "android",
        "blackberry",
        "ipad",
        "iphone",
        "symbian",
    ]


def get_browser() -> Browser:
    if is_mobile():
        return Browser.Other

    user_agent = request.user_agent
    if user_agent.browser == "edge":
        return Browser.Edge
    elif user_agent.browser in ["chrome", "opera", "webkit"]:
        return Browser.Chrome
    elif user_agent.browser in ["mozilla", "firefox"]:
        return Browser.Firefox
    return Browser.Other


@onboarding_bp.route("/account_activated", methods=["GET"])
@login_required
def account_activated():
    browser = get_browser()
    if browser == Browser.Chrome:
        extension_link = CHROME_EXTENSION_LINK
        browser_name = "Chrome"
    elif browser == Browser.Firefox:
        extension_link = FIREFOX_EXTENSION_LINK
        browser_name = "Firefox"
    elif browser == Browser.Edge:
        extension_link = EDGE_EXTENSION_LINK
        browser_name = "Edge"
    else:
        return redirect(url_for("dashboard.index"))

    return render_template(
        "onboarding/account_activated.html",
        extension_link=extension_link,
        browser_name=browser_name,
    )

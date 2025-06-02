from dataclasses import dataclass
from enum import Enum
from flask import request
from typing import Optional

CHROME_EXTENSION_LINK = "https://chrome.google.com/webstore/detail/simpleloginreceive-send-e/dphilobhebphkdjbpfohgikllaljmgbn"
FIREFOX_EXTENSION_LINK = "https://addons.mozilla.org/firefox/addon/simplelogin/"
EDGE_EXTENSION_LINK = "https://microsoftedge.microsoft.com/addons/detail/simpleloginreceive-sen/diacfpipniklenphgljfkmhinphjlfff"


@dataclass
class ExtensionInfo:
    browser: str
    url: str


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


def get_extension_info() -> Optional[ExtensionInfo]:
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
        return None
    return ExtensionInfo(
        browser=browser_name,
        url=extension_link,
    )

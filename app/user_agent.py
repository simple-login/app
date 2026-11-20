"""User agent parsing.

Werkzeug >= 2.1 removed its built-in user agent parser, so
`request.user_agent.browser/platform` are always None. This is a port of the
Werkzeug 1.0 parser (werkzeug/useragents.py, BSD-3-Clause, (c) 2007 Pallets) so
browser detection keeps working exactly as before.
"""

import re
from typing import Optional, Tuple

from werkzeug.user_agent import UserAgent

_PLATFORMS = (
    (" cros ", "chromeos"),
    ("iphone|ios", "iphone"),
    ("ipad", "ipad"),
    (r"darwin|mac|os\s*x", "macos"),
    ("win", "windows"),
    (r"android", "android"),
    ("netbsd", "netbsd"),
    ("openbsd", "openbsd"),
    ("freebsd", "freebsd"),
    ("dragonfly", "dragonflybsd"),
    ("(sun|i86)os", "solaris"),
    (r"x11|lin(\b|ux)?", "linux"),
    (r"nintendo\s+wii", "wii"),
    ("irix", "irix"),
    ("hp-?ux", "hpux"),
    ("aix", "aix"),
    ("sco|unix_sv", "sco"),
    ("bsd", "bsd"),
    ("amiga", "amiga"),
    ("blackberry|playbook", "blackberry"),
    ("symbian", "symbian"),
)

_BROWSERS = (
    ("googlebot", "google"),
    ("msnbot", "msn"),
    ("yahoo", "yahoo"),
    ("ask jeeves", "ask"),
    (r"aol|america\s+online\s+browser", "aol"),
    (r"opera|opr", "opera"),
    ("edge", "edge"),
    ("chrome|crios", "chrome"),
    ("seamonkey", "seamonkey"),
    ("firefox|firebird|phoenix|iceweasel", "firefox"),
    ("galeon", "galeon"),
    ("safari|version", "safari"),
    ("webkit", "webkit"),
    ("camino", "camino"),
    ("konqueror", "konqueror"),
    ("k-meleon", "kmeleon"),
    ("netscape", "netscape"),
    (r"msie|microsoft\s+internet\s+explorer|trident/.+? rv:", "msie"),
    ("lynx", "lynx"),
    ("links", "links"),
    ("Baiduspider", "baidu"),
    ("bingbot", "bing"),
    ("mozilla", "mozilla"),
)

_BROWSER_VERSION_RE = r"(?:%s)[/\sa-z(]*(\d+[.\da-z]+)?"
_LANGUAGE_RE = re.compile(
    r"(?:;\s*|\s+)(\b\w{2}\b(?:-\b\w{2}\b)?)\s*;|"
    r"(?:\(|\[|;)\s*(\b\w{2}\b(?:-\b\w{2}\b)?)\s*(?:\]|\)|;)"
)
_PLATFORM_REGEXES = [(name, re.compile(rx, re.I)) for rx, name in _PLATFORMS]
_BROWSER_REGEXES = [
    (name, re.compile(_BROWSER_VERSION_RE % rx, re.I)) for rx, name in _BROWSERS
]


def parse_user_agent(
    user_agent: str,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return (platform, browser, version, language)"""
    platform = None
    for name, regex in _PLATFORM_REGEXES:
        if regex.search(user_agent):
            platform = name
            break

    browser = version = None
    for name, regex in _BROWSER_REGEXES:
        match = regex.search(user_agent)
        if match is not None:
            browser = name
            version = match.group(1)
            break

    language = None
    match = _LANGUAGE_RE.search(user_agent)
    if match is not None:
        language = match.group(1) or match.group(2)

    return platform, browser, version, language


class ParsedUserAgent(UserAgent):
    def __init__(self, string: str) -> None:
        super().__init__(string)
        self.platform, self.browser, self.version, self.language = parse_user_agent(
            string
        )

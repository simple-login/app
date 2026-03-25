import re

import re2

from app.log import LOG


_SENDER_BLACKLIST_ALLOWED_RE = re.compile(r"^[A-Za-z0-9@._\-\+\*\^\$\(\)\|\?\[\]\\]+$")


def validate_sender_blacklist_pattern(pattern: str) -> str | None:
    """Validate a user-provided sender-blacklist regex pattern.

    The goal is to keep patterns simple and prevent expensive/unsafe constructs.
    We also validate the regex compiles (re2 preferred).

    Returns:
        None if valid; otherwise an error message string.
    """
    if not pattern:
        return "Pattern cannot be empty"

    # Keep the allowed character set intentionally small.
    if not _SENDER_BLACKLIST_ALLOWED_RE.fullmatch(pattern):
        return (
            "Invalid characters in pattern. Allowed: letters, digits, and @ . _ - + * ^ $ ( ) | ? [ ] \\"
        )

    try:
        re2.compile(pattern)
    except Exception:
        return "Invalid regex pattern"

    return None


def regex_match(rule_regex: str, local) -> bool:
    """Return True if *full string* matches rule_regex."""
    regex = re2.compile(rule_regex)
    try:
        if re2.fullmatch(regex, local):
            return True
    except TypeError:  # re2 bug "Argument 'pattern' has incorrect type (expected bytes, got PythonRePattern)"
        LOG.w("use re instead of re2 for %s %s", rule_regex, local)
        regex = re.compile(rule_regex)
        if re.fullmatch(regex, local):
            return True
    return False


def regex_search(rule_regex: str, text: str) -> bool:
    """Return True if any substring of text matches rule_regex.

    Uses re2 when possible to avoid catastrophic backtracking.
    """
    regex = re2.compile(rule_regex)
    try:
        if re2.search(regex, text):
            return True
    except TypeError:  # re2 bug "Argument 'pattern' has incorrect type (expected bytes, got PythonRePattern)"
        LOG.w("use re instead of re2 for %s %s", rule_regex, text)
        regex = re.compile(rule_regex)
        if re.search(regex, text):
            return True
    return False

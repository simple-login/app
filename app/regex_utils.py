import re

import re2

from app.log import LOG


# Keep this permissive enough for practical regexes, but still a strict whitelist.
# Note: We intentionally do NOT allow whitespace.
_SENDER_BLACKLIST_ALLOWED_RE = re.compile(
    r"^[A-Za-z0-9\[\]\{\}\(\)\|\?\^\$@,._\-\+\*\\\.]+$"
)


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
            "Invalid characters in pattern. Allowed: letters, digits, and []{}(),._-+*\\.^$@|?"
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


def is_safe_regex_pattern(pattern: str, context: str = "") -> bool:
    """Validate regex pattern to prevent ReDoS attacks.

    Checks for:
    - Maximum length (prevent extremely long patterns)
    - Nested quantifiers (e.g., (a+)+, (a*)*)
    - Excessive backtracking potential

    Args:
        pattern: The regex pattern to validate
        context: Optional context string for logging (e.g., "in email search")

    Returns:
        True if the pattern is safe to use, False otherwise
    """
    if not pattern or len(pattern) > 100:
        return False

    # Check for nested quantifiers which cause exponential backtracking
    # Patterns like (a+)+, (a*)*, (a?)*, etc.
    nested_quantifier_pattern = r"\([^)]*[+*?]\)[+*?]"
    if re.search(nested_quantifier_pattern, pattern):
        LOG.w(f"Potentially dangerous regex pattern detected{context}: {pattern}")
        return False

    # Check for excessive alternation with wildcards
    # Patterns like (a|b|c|d|...)* with many alternatives
    alternation_pattern = r"\([^)]*(\|[^)]*){10,}\)[+*?]"
    if re.search(alternation_pattern, pattern):
        LOG.w(f"Excessive alternation in regex pattern{context}: {pattern}")
        return False

    # Try to compile the pattern to catch syntax errors
    try:
        re.compile(pattern)
    except re.error as e:
        LOG.w(f"Invalid regex pattern{context}: {pattern} - {e}")
        return False

    return True

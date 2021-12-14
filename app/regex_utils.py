import re

import re2

from app.log import LOG


def regex_match(rule_regex: str, local):
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

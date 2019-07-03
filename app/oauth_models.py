import enum
from typing import Set, Union

import flask


class ScopeE(enum.Enum):
    """ScopeE to distinguish with Scope model"""

    EMAIL = "email"
    NAME = "name"
    OPENID = "openid"
    AVATAR_URL = "avatar_url"


class ResponseType(enum.Enum):
    CODE = "code"
    TOKEN = "token"
    ID_TOKEN = "id_token"


def get_scopes(request: flask.Request) -> Set[ScopeE]:
    scope_strs = _split_arg(request.args.getlist("scope"))

    return set([ScopeE(scope_str) for scope_str in scope_strs])


def get_response_types(request: flask.Request) -> Set[ResponseType]:
    response_type_strs = _split_arg(request.args.getlist("response_type"))

    return set([ResponseType(r) for r in response_type_strs])


def _split_arg(arg_input: Union[str, list]) -> Set[str]:
    """convert input response_type/scope into a set of string.
    arg_input = request.args.getlist(response_type|scope)
    Take into account different variations and their combinations
    - the split character is " " or ","
    - the response_type/scope passed as a list ?scope=scope_1&scope=scope_2
    """
    res = set()
    if type(arg_input) is str:
        if " " in arg_input:
            for x in arg_input.split(" "):
                if x:
                    res.add(x.lower())
        elif "," in arg_input:
            for x in arg_input.split(","):
                if x:
                    res.add(x.lower())
        else:
            res.add(arg_input)

    else:
        for arg in arg_input:
            res = res.union(_split_arg(arg))

    return res

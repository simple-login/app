class AliasInTrashError(Exception):
    """raised when alias is deleted before """

    pass


class DirectoryInTrashError(Exception):
    """raised when a directory is deleted before """

    pass


class SubdomainInTrashError(Exception):
    """raised when a subdomain is deleted before """

    pass

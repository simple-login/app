class AliasInTrashError(Exception):
    """raised when alias is deleted before """

    pass


class DirectoryInTrashError(Exception):
    """raised when a directory is deleted before """

    pass


class SubdomainInTrashError(Exception):
    """raised when a subdomain is deleted before """

    pass


class CannotCreateContactForReverseAlias(Exception):
    """raised when a contact is created that has website_email=reverse_alias of another contact"""

    pass


class NonReverseAliasInReplyPhase(Exception):
    """raised when a non reverse-alias is used during a reply phase"""

    pass


class VERPTransactional(Exception):
    """raised an email sent to a transactional VERP can't be handled"""

    pass


class VERPForward(Exception):
    """raised an email sent to a forward VERP can't be handled"""

    pass


class VERPReply(Exception):
    """raised an email sent to a reply VERP can't be handled"""

    pass


class MailSentFromReverseAlias(Exception):
    """raised when receiving an email sent from a reverse alias"""

    pass

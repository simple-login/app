class SLException(Exception):
    def __str__(self):
        super_str = super().__str__()
        return f"{type(self).__name__} {super_str}"


class AliasInTrashError(SLException):
    """raised when alias is deleted before"""

    pass


class DirectoryInTrashError(SLException):
    """raised when a directory is deleted before"""

    pass


class SubdomainInTrashError(SLException):
    """raised when a subdomain is deleted before"""

    pass


class CannotCreateContactForReverseAlias(SLException):
    """raised when a contact is created that has website_email=reverse_alias of another contact"""

    pass


class NonReverseAliasInReplyPhase(SLException):
    """raised when a non reverse-alias is used during a reply phase"""

    pass


class VERPTransactional(SLException):
    """raised an email sent to a transactional VERP can't be handled"""

    pass


class VERPForward(SLException):
    """raised an email sent to a forward VERP can't be handled"""

    pass


class VERPReply(SLException):
    """raised an email sent to a reply VERP can't be handled"""

    pass


class MailSentFromReverseAlias(SLException):
    """raised when receiving an email sent from a reverse alias"""

    pass

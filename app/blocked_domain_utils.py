from app.models import BlockedDomain


def is_domain_blocked(user_id: int, domain: str) -> bool:
    """checks whether the provided domain is blocked for a given user"""
    return BlockedDomain.filter_by(user_id=user_id, domain=domain).first() is not None

from app.events.event_dispatcher import Dispatcher
from app.models import PartnerUser, User
from app.proton.utils import get_proton_partner
from tests.utils import create_new_user, random_token
from typing import Tuple


class OnMemoryDispatcher(Dispatcher):
    def __init__(self):
        self.memory = []

    def send(self, event: bytes):
        self.memory.append(event)

    def clear(self):
        self.memory = []


def _create_unlinked_user() -> User:
    return create_new_user()


def _create_linked_user() -> Tuple[User, PartnerUser]:
    user = _create_unlinked_user()
    partner_user = PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )

    return user, partner_user

from app.events.event_dispatcher import Dispatcher
from app.events.generated import event_pb2
from app.models import PartnerUser, User
from app.proton.proton_partner import get_proton_partner
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


def _get_event_from_string(
    data: str, user: User, pu: PartnerUser
) -> event_pb2.EventContent:
    event = event_pb2.Event()
    event.ParseFromString(data)
    assert user.id == event.user_id
    assert pu.external_user_id == event.external_user_id
    assert pu.partner_id == event.partner_id
    return event.content

from abc import ABC, abstractmethod
from app import config
from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.events.generated import event_pb2
from app.models import User, PartnerUser, SyncEvent
from app.proton.utils import get_proton_partner
from typing import Optional

NOTIFICATION_CHANNEL = "simplelogin_sync_events"


class Dispatcher(ABC):
    @abstractmethod
    def send(self, event: bytes):
        pass


class PostgresDispatcher(Dispatcher):
    def send(self, event: bytes):
        instance = SyncEvent.create(content=event, flush=True)
        Session.execute(f"NOTIFY {NOTIFICATION_CHANNEL}, '{instance.id}';")

    @staticmethod
    def get():
        return PostgresDispatcher()


class EventDispatcher:
    @staticmethod
    def send_event(
        user: User,
        content: event_pb2.EventContent,
        dispatcher: Dispatcher = PostgresDispatcher.get(),
        skip_if_webhook_missing: bool = True,
    ):
        if config.EVENT_WEBHOOK_DISABLE:
            return

        if not config.EVENT_WEBHOOK and skip_if_webhook_missing:
            return

        partner_user = EventDispatcher.__partner_user(user.id)
        if not partner_user:
            return

        event = event_pb2.Event(
            user_id=user.id,
            external_user_id=partner_user.external_user_id,
            partner_id=partner_user.partner_id,
            content=content,
        )

        serialized = event.SerializeToString()
        dispatcher.send(serialized)

    @staticmethod
    def __partner_user(user_id: int) -> Optional[PartnerUser]:
        # Check if the current user has a partner_id
        try:
            proton_partner_id = get_proton_partner().id
        except ProtonPartnerNotSetUp:
            return None

        # It has. Retrieve the information for the PartnerUser
        return PartnerUser.get_by(user_id=user_id, partner_id=proton_partner_id)

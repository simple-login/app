from abc import ABC, abstractmethod

import newrelic.agent

from app import config
from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.events.generated import event_pb2
from app.log import LOG
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


class GlobalDispatcher:
    __dispatcher: Optional[Dispatcher] = None

    @staticmethod
    def get_dispatcher() -> Dispatcher:
        if not GlobalDispatcher.__dispatcher:
            GlobalDispatcher.__dispatcher = PostgresDispatcher.get()
        return GlobalDispatcher.__dispatcher

    @staticmethod
    def set_dispatcher(dispatcher: Optional[Dispatcher]):
        GlobalDispatcher.__dispatcher = dispatcher


class EventDispatcher:
    @staticmethod
    def send_event(
        user: User,
        content: event_pb2.EventContent,
        dispatcher: Optional[Dispatcher] = None,
        skip_if_webhook_missing: bool = True,
    ):
        if dispatcher is None:
            dispatcher = GlobalDispatcher.get_dispatcher()
        if config.EVENT_WEBHOOK_DISABLE:
            LOG.d("Not sending events because webhook is disabled")
            return

        if not config.EVENT_WEBHOOK and skip_if_webhook_missing:
            LOG.d(
                "Not sending events because webhook is not configured and allowed to be empty"
            )
            return

        partner_user = EventDispatcher.__partner_user(user.id)
        if not partner_user:
            LOG.d(f"Not sending events because there's no partner user for user {user}")
            return

        event = event_pb2.Event(
            user_id=user.id,
            external_user_id=partner_user.external_user_id,
            partner_id=partner_user.partner_id,
            content=content,
        )

        serialized = event.SerializeToString()
        dispatcher.send(serialized)

        event_type = content.WhichOneof("content")
        newrelic.agent.record_custom_event("EventStoredToDb", {"type": event_type})
        LOG.i("Sent event to the dispatcher")

    @staticmethod
    def __partner_user(user_id: int) -> Optional[PartnerUser]:
        # Check if the current user has a partner_id
        try:
            proton_partner_id = get_proton_partner().id
        except ProtonPartnerNotSetUp:
            return None

        # It has. Retrieve the information for the PartnerUser
        return PartnerUser.get_by(user_id=user_id, partner_id=proton_partner_id)

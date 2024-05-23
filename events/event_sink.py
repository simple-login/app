import requests

from abc import ABC, abstractmethod
from app.config import EVENT_WEBHOOK, EVENT_WEBHOOK_SKIP_VERIFY_SSL
from app.log import LOG
from app.models import SyncEvent


class EventSink(ABC):
    @abstractmethod
    def process(self, event: SyncEvent) -> bool:
        pass


class HttpEventSink(EventSink):
    def process(self, event: SyncEvent) -> bool:
        if not EVENT_WEBHOOK:
            LOG.warning("Skipping sending event because there is no webhook configured")
            return False

        LOG.info(f"Sending event {event.id} to {EVENT_WEBHOOK}")

        res = requests.post(
            url=EVENT_WEBHOOK,
            data=event.content,
            headers={"Content-Type": "application/x-protobuf"},
            verify=not EVENT_WEBHOOK_SKIP_VERIFY_SSL,
        )
        if res.status_code != 200:
            LOG.warning(
                f"Failed to send event to webhook: {res.status_code} {res.text}"
            )
            return False
        else:
            LOG.info(f"Event {event.id} sent successfully to webhook")
            return True


class ConsoleEventSink(EventSink):
    def process(self, event: SyncEvent) -> bool:
        LOG.info(f"Handling event {event.id}")
        return True

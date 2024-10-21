import requests
import newrelic.agent

from abc import ABC, abstractmethod
from app.config import EVENT_WEBHOOK, EVENT_WEBHOOK_SKIP_VERIFY_SSL
from app.log import LOG
from app.models import SyncEvent


class EventSink(ABC):
    @abstractmethod
    def process(self, event: SyncEvent) -> bool:
        pass

    @abstractmethod
    def send_data_to_webhook(self, data: bytes) -> bool:
        pass


class HttpEventSink(EventSink):
    def process(self, event: SyncEvent) -> bool:
        if not EVENT_WEBHOOK:
            LOG.warning("Skipping sending event because there is no webhook configured")
            return False

        LOG.info(f"Sending event {event.id} to {EVENT_WEBHOOK}")

        if self.send_data_to_webhook(event.content):
            LOG.info(f"Event {event.id} sent successfully to webhook")
            return True

        return False

    def send_data_to_webhook(self, data: bytes) -> bool:
        res = requests.post(
            url=EVENT_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/x-protobuf"},
            verify=not EVENT_WEBHOOK_SKIP_VERIFY_SSL,
        )
        newrelic.agent.record_custom_event(
            "EventSentToPartner", {"http_code": res.status_code}
        )
        if res.status_code != 200:
            LOG.warning(
                f"Failed to send event to webhook: {res.status_code} {res.text}"
            )
            return False
        else:
            return True


class ConsoleEventSink(EventSink):
    def process(self, event: SyncEvent) -> bool:
        LOG.info(f"Handling event {event.id}")
        return True

    def send_data_to_webhook(self, data: bytes) -> bool:
        LOG.info(f"Sending {len(data)} bytes to webhook")
        return True

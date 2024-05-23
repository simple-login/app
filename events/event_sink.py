from abc import ABC, abstractmethod
from app.log import LOG
from app.models import SyncEvent


class EventSink(ABC):
    @abstractmethod
    def process(self, event: SyncEvent):
        pass


class HttpEventSink(EventSink):
    def process(self, event: SyncEvent):
        pass


class ConsoleEventSink(EventSink):
    def process(self, event: SyncEvent):
        LOG.info(f"Handling event {event.id}")

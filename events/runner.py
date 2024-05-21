from app.log import LOG
from app.models import SyncEvent
from events.event_sink import EventSink
from events.event_source import EventSource


class Runner:
    def __init__(self, source: EventSource, sink: EventSink):
        self.__source = source
        self.__sink = sink

    def run(self):
        self.__source.run(self.__on_event)

    def __on_event(self, event: SyncEvent):
        try:
            can_process = event.mark_as_taken()
            if can_process:
                self.__sink.process(event)
                event_id = event.id
                SyncEvent.delete(event.id, commit=True)
                LOG.info(f"Marked {event_id} as done")
            else:
                LOG.info(f"{event.id} was handled by another runner")
        except Exception as e:
            LOG.warn(f"Exception processing event [id={event.id}]: {e}")

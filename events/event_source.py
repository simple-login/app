import arrow
import newrelic.agent
import psycopg2
import select

from abc import ABC, abstractmethod
from app.log import LOG
from app.models import SyncEvent
from app.events.event_dispatcher import NOTIFICATION_CHANNEL
from time import sleep
from typing import Callable, NoReturn

_DEAD_LETTER_THRESHOLD_MINUTES = 10
_DEAD_LETTER_INTERVAL_SECONDS = 30


class EventSource(ABC):
    @abstractmethod
    def run(self, on_event: Callable[[SyncEvent], NoReturn]):
        pass


class PostgresEventSource(EventSource):
    def __init__(self, connection_string: str):
        self.__connection = psycopg2.connect(connection_string)

    def run(self, on_event: Callable[[SyncEvent], NoReturn]):
        self.__connection.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
        )

        cursor = self.__connection.cursor()
        cursor.execute(f"LISTEN {NOTIFICATION_CHANNEL};")

        while True:
            if select.select([self.__connection], [], [], 5) != ([], [], []):
                self.__connection.poll()
                while self.__connection.notifies:
                    notify = self.__connection.notifies.pop(0)
                    LOG.debug(
                        f"Got NOTIFY: pid={notify.pipd} channel={notify.channel} payload={notify.payload}"
                    )
                    try:
                        webhook_id = int(notify.payload)
                        event = SyncEvent.get_by(id=webhook_id)
                        if event is not None:
                            on_event(event)
                        else:
                            LOG.info(f"Could not find event with id={notify.payload}")
                    except Exception as e:
                        LOG.warn(f"Error getting event: {e}")


class DeadLetterEventSource(EventSource):
    @newrelic.agent.background_task()
    def run(self, on_event: Callable[[SyncEvent], NoReturn]):
        while True:
            try:
                threshold = arrow.utcnow().shift(
                    minutes=-_DEAD_LETTER_THRESHOLD_MINUTES
                )
                events = SyncEvent.get_dead_letter(older_than=threshold)
                if events is not None:
                    LOG.info(f"Got {len(events)} dead letter events")
                    if events:
                        newrelic.agent.record_custom_metric(
                            "Custom/dead_letter_events_to_process", len(events)
                        )
                    for event in events:
                        on_event(event)
                else:
                    LOG.debug("No dead letter events")
                    sleep(_DEAD_LETTER_INTERVAL_SECONDS)
            except Exception as e:
                LOG.warn(f"Error getting dead letter event: {e}")

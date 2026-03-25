import arrow
import newrelic.agent
import psycopg2
import select

from abc import ABC, abstractmethod

from app.db import Session
from app.log import LOG
from app.models import SyncEvent
from app.events.event_dispatcher import NOTIFICATION_CHANNEL
from time import sleep
from typing import Callable, NoReturn

_DEAD_LETTER_THRESHOLD_MINUTES = 10
_DEAD_LETTER_INTERVAL_SECONDS = 30

_POSTGRES_RECONNECT_INTERVAL_SECONDS = 5


class EventSource(ABC):
    @abstractmethod
    def run(self, on_event: Callable[[SyncEvent], NoReturn]):
        pass


class PostgresEventSource(EventSource):
    def __init__(self, connection_string: str):
        self.__connection_string = connection_string
        self.__connect()

    def run(self, on_event: Callable[[SyncEvent], NoReturn]):
        while True:
            try:
                self.__listen(on_event)
            except Exception as e:
                LOG.warning(f"Error listening to events: {e}")
                sleep(_POSTGRES_RECONNECT_INTERVAL_SECONDS)
                self.__connect()

    def __listen(self, on_event: Callable[[SyncEvent], NoReturn]):
        self.__connection.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
        )

        cursor = self.__connection.cursor()
        cursor.execute(f"LISTEN {NOTIFICATION_CHANNEL};")

        LOG.info("Starting to listen to events")
        while True:
            if select.select([self.__connection], [], [], 5) != ([], [], []):
                self.__connection.poll()
                while self.__connection.notifies:
                    notify = self.__connection.notifies.pop(0)
                    LOG.debug(
                        f"Got NOTIFY: pid={notify.pid} channel={notify.channel} payload={notify.payload}"
                    )
                    try:
                        webhook_id = int(notify.payload)
                        event = SyncEvent.get_by(id=webhook_id)
                        if event is not None:
                            if event.mark_as_taken():
                                on_event(event)
                            else:
                                LOG.info(
                                    f"Event {event.id} was handled by another runner"
                                )
                        else:
                            LOG.info(f"Could not find event with id={notify.payload}")
                    except Exception as e:
                        LOG.warning(f"Error getting event: {e}")
                    Session.close()  # Ensure we get a new connection and we don't leave a dangling tx

    def __connect(self):
        self.__connection = psycopg2.connect(
            self.__connection_string, application_name="sl-event-listen"
        )

        from app.db import Session

        Session.close()


class DeadLetterEventSource(EventSource):
    def __init__(self, max_retries: int):
        self.__max_retries = max_retries

    def execute_loop(
        self, on_event: Callable[[SyncEvent], NoReturn]
    ) -> list[SyncEvent]:
        threshold = arrow.utcnow().shift(minutes=-_DEAD_LETTER_THRESHOLD_MINUTES)
        events = SyncEvent.get_dead_letter(
            older_than=threshold, max_retries=self.__max_retries
        )
        if events:
            LOG.info(f"Got {len(events)} dead letter events")
            newrelic.agent.record_custom_metric(
                "Custom/dead_letter_events_to_process", len(events)
            )
            for event in events:
                if event.mark_as_taken(allow_taken_older_than=threshold):
                    on_event(event)
        return events

    @newrelic.agent.background_task()
    def run(self, on_event: Callable[[SyncEvent], NoReturn]):
        while True:
            try:
                events = self.execute_loop(on_event)
                Session.close()  # Ensure that we have a new connection and we don't have a dangling tx with a lock
                if not events:
                    LOG.debug("No dead letter events")
                    sleep(_DEAD_LETTER_INTERVAL_SECONDS)
            except Exception as e:
                LOG.warning(f"Error getting dead letter event: {e}")
                sleep(_DEAD_LETTER_INTERVAL_SECONDS)

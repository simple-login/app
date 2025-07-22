import newrelic.agent

from app.events.event_dispatcher import EventDispatcher, Dispatcher
from app.events.generated.event_pb2 import EventContent, AliasCreated, AliasCreatedList
from app.log import LOG
from app.models import User, Alias


def send_alias_creation_events_for_user(
    user: User, dispatcher: Dispatcher, chunk_size=50
):
    if user.disabled:
        LOG.i("User {user} is disabled. Skipping sending events for that user")
        return
    chunk_size = min(chunk_size, 50)
    event_list = []
    LOG.i("Sending alias create events for user {user}")
    for alias in (
        Alias.filter_by(user_id=user.id)
        .enable_eagerloads(False)
        .yield_per(chunk_size)
        .order_by(Alias.id.asc())
    ):
        event_list.append(
            AliasCreated(
                id=alias.id,
                email=alias.email,
                note=alias.note,
                enabled=alias.enabled,
                created_at=int(alias.created_at.timestamp),
            )
        )
        if len(event_list) >= chunk_size:
            LOG.i(f"Sending {len(event_list)} alias create event for {user}")
            EventDispatcher.send_event(
                user,
                EventContent(alias_create_list=AliasCreatedList(events=event_list)),
                dispatcher=dispatcher,
            )
            newrelic.agent.record_custom_metric(
                "Custom/event_alias_created_event", len(event_list)
            )
            event_list = []
    if len(event_list) > 0:
        LOG.i(f"Sending {len(event_list)} alias create event for {user}")
        EventDispatcher.send_event(
            user,
            EventContent(alias_create_list=AliasCreatedList(events=event_list)),
            dispatcher=dispatcher,
        )
        newrelic.agent.record_custom_metric(
            "Custom/event_alias_created_event", len(event_list)
        )

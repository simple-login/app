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
    for alias in (
        Alias.yield_per_query(chunk_size)
        .filter_by(user_id=user.id)
        .order_by(Alias.id.asc())
    ):
        event_list.append(
            AliasCreated(
                alias_id=alias.id,
                alias_email=alias.email,
                alias_note=alias.note,
                enabled=alias.enabled,
            )
        )
        if len(event_list) >= chunk_size:
            EventDispatcher.send_event(
                user,
                EventContent(alias_create_list=AliasCreatedList(events=event_list)),
                dispatcher=dispatcher,
            )
            event_list = []
    if len(event_list) > 0:
        EventDispatcher.send_event(
            user,
            EventContent(alias_create_list=AliasCreatedList(events=event_list)),
            dispatcher=dispatcher,
        )

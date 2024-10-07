from app.events.generated import event_pb2
from app.models import SyncEvent
from events.event_sink import HttpEventSink


def debug_event(event_id: int):
    event = SyncEvent.get_by(id=event_id)
    if not event:
        print("Event not found")
        return

    print(f"Info for event {event_id}")
    print(f"- Created at: {event.created_at}")
    print(f"- Updated at: {event.updated_at}")
    print(f"- Taken time: {event.taken_time}")
    print(f"- Retry count: {event.retry_count}")

    print()
    print("Event contents")
    event_contents = event.content
    parsed = event_pb2.Event.FromString(event_contents)

    print(f"- UserID: {parsed.user_id}")
    print(f"- ExternalUserID: {parsed.external_user_id}")
    print(f"- PartnerID: {parsed.partner_id}")

    content = parsed.content
    print(f"Content: {content}")


def run_event(event_id: int, delete_on_success: bool = True):
    event = SyncEvent.get_by(id=event_id)
    if not event:
        print("Event not found")
        return

    print(f"Processing event {event_id}")
    sink = HttpEventSink()
    res = sink.process(event)
    if res:
        print(f"Processed event {event_id}")
        if delete_on_success:
            SyncEvent.delete(event_id, commit=True)

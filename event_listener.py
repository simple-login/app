import argparse
from enum import Enum
from sys import argv, exit

from app.config import EVENT_LISTENER_DB_URI
from app.log import LOG
from app.monitor_utils import send_version_event
from events import event_debugger
from events.runner import Runner
from events.event_source import DeadLetterEventSource, PostgresEventSource
from events.event_sink import ConsoleEventSink, HttpEventSink

_DEFAULT_MAX_RETRIES = 10


class Mode(Enum):
    DEAD_LETTER = "dead_letter"
    LISTENER = "listener"

    @staticmethod
    def from_str(value: str):
        if value == Mode.DEAD_LETTER.value:
            return Mode.DEAD_LETTER
        elif value == Mode.LISTENER.value:
            return Mode.LISTENER
        else:
            raise ValueError(f"Invalid mode: {value}")


def main(mode: Mode, dry_run: bool, max_retries: int):
    if mode == Mode.DEAD_LETTER:
        LOG.i("Using DeadLetterEventSource")
        source = DeadLetterEventSource(max_retries)
        service_name = "event_listener_dead_letter"
    elif mode == Mode.LISTENER:
        LOG.i("Using PostgresEventSource")
        source = PostgresEventSource(EVENT_LISTENER_DB_URI)
        service_name = "event_listener"
    else:
        raise ValueError(f"Invalid mode: {mode}")

    if dry_run:
        LOG.i("Starting with ConsoleEventSink")
        sink = ConsoleEventSink()
    else:
        LOG.i("Starting with HttpEventSink")
        sink = HttpEventSink()

    send_version_event(service_name)
    runner = Runner(source=source, sink=sink, service_name=service_name)
    runner.run()


def debug_event(event_id: str):
    LOG.i(f"Debugging event {event_id}")
    try:
        event_id_int = int(event_id)
    except ValueError:
        raise ValueError(f"Invalid event id: {event_id}")
    event_debugger.debug_event(event_id_int)


def run_event(event_id: str, delete_on_success: bool):
    LOG.i(f"Running event {event_id}")
    try:
        event_id_int = int(event_id)
    except ValueError:
        raise ValueError(f"Invalid event id: {event_id}")
    event_debugger.run_event(event_id_int, delete_on_success)


def args():
    parser = argparse.ArgumentParser(description="Run event listener")
    subparsers = parser.add_subparsers(dest="command")

    listener_parser = subparsers.add_parser(Mode.LISTENER.value)
    listener_parser.add_argument(
        "--max-retries", type=int, default=_DEFAULT_MAX_RETRIES
    )
    listener_parser.add_argument("--dry-run", action="store_true")

    dead_letter_parser = subparsers.add_parser(Mode.DEAD_LETTER.value)
    dead_letter_parser.add_argument(
        "--max-retries", type=int, default=_DEFAULT_MAX_RETRIES
    )
    dead_letter_parser.add_argument("--dry-run", action="store_true")

    debug_parser = subparsers.add_parser("debug")
    debug_parser.add_argument("event_id", help="ID of the event to debug")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("event_id", help="ID of the event to run")
    run_parser.add_argument("--delete-on-success", action="store_true")

    return parser.parse_args()


if __name__ == "__main__":
    if len(argv) < 2:
        print("Invalid usage. Pass a valid subcommand as argument")
        exit(1)

    args = args()

    if args.command in [Mode.LISTENER.value, Mode.DEAD_LETTER.value]:
        main(
            mode=Mode.from_str(args.command),
            dry_run=args.dry_run,
            max_retries=args.max_retries,
        )
    elif args.command == "debug":
        debug_event(args.event_id)
    elif args.command == "run":
        run_event(args.event_id, args.delete_on_success)
    else:
        print("Invalid command")
        exit(1)

import argparse
from enum import Enum
from sys import argv, exit

from app.config import DB_URI
from app.log import LOG
from events.runner import Runner
from events.event_source import DeadLetterEventSource, PostgresEventSource
from events.event_sink import ConsoleEventSink, HttpEventSink

_DEFAULT_MAX_RETRIES = 100


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
    elif mode == Mode.LISTENER:
        LOG.i("Using PostgresEventSource")
        source = PostgresEventSource(DB_URI)
    else:
        raise ValueError(f"Invalid mode: {mode}")

    if dry_run:
        LOG.i("Starting with ConsoleEventSink")
        sink = ConsoleEventSink()
    else:
        LOG.i("Starting with HttpEventSink")
        sink = HttpEventSink()

    runner = Runner(source=source, sink=sink)
    runner.run()


def args():
    parser = argparse.ArgumentParser(description="Run event listener")
    parser.add_argument(
        "mode",
        help="Mode to run",
        choices=[Mode.DEAD_LETTER.value, Mode.LISTENER.value],
    )
    parser.add_argument(
        "max_retries",
        help="Max retries to consider an event as error and not try to process it again",
        type=int,
        nargs="?",
        default=_DEFAULT_MAX_RETRIES,
    )
    parser.add_argument("--dry-run", help="Dry run mode", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    if len(argv) < 2:
        print("Invalid usage. Pass 'listener' or 'dead_letter' as argument")
        exit(1)

    args = args()
    main(
        mode=Mode.from_str(args.mode),
        dry_run=args.dry_run,
        max_retries=args.max_retries,
    )

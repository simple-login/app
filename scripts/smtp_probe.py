"""Health/readiness probe client for the email handler, usable as a k8s exec probe.

    python scripts/smtp_probe.py health|ready [--host H] [--port P] [--timeout S]

Exits 0 only if the server replies with the expected code *and* marker text, so
a plain SMTP server answering ``250 OK`` to everything is reported as failing.
Only EHLO/MAIL/RCPT are sent, never DATA.
Probe addresses are read from the env and the ``CONFIG``/``.env`` file, like app/config.py.
"""

import argparse
import os
import smtplib
import sys
from typing import Tuple

ROOT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

# Keep in sync with app/email_probe.py
EXPECTED = {
    "health": (
        "EMAIL_HANDLER_HEALTH_ADDRESS",
        "health@probe.invalid",
        250,
        b"2.0.0 SL-PROBE HEALTH OK",
    ),
    "ready": (
        "EMAIL_HANDLER_READY_ADDRESS",
        "ready@probe.invalid",
        250,
        b"2.0.0 SL-PROBE READY OK",
    ),
}


def load_config() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    config_file = os.environ.get("CONFIG")
    if config_file:
        if not config_file.startswith("/"):
            config_file = os.path.join(ROOT_DIR, config_file)
        load_dotenv(config_file)
    else:
        load_dotenv(os.path.join(ROOT_DIR, ".env"))


def probe(mode: str, host: str, port: int, timeout: float) -> int:
    env_var, default, code, marker = EXPECTED[mode]
    address = os.environ.get(env_var, default)
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            smtp.mail("<>")
            reply: Tuple[int, bytes] = smtp.docmd("RCPT", f"TO:<{address}>")
    except (OSError, smtplib.SMTPException) as e:
        print(f"{mode} probe failed: {e}", file=sys.stderr)
        return 1
    if reply != (code, marker):
        print(f"{mode} probe got unexpected reply: {reply}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=sorted(EXPECTED))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=20381)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    load_config()
    return probe(args.mode, args.host, args.port, args.timeout)


if __name__ == "__main__":
    sys.exit(main())

"""Readiness probe client for the web app, usable as a k8s exec probe.

    python -m scripts.http_probe [--scheme http|https] [--host H] [--port P] [--path P] [--timeout S]

Sends ``GET /health/ready`` with the ``READINESS_TOKEN`` bearer token from
app/config.py and exits 0 only on a 200 reply. The probe targets the pod itself,
so TLS certificates are not verified and proxy env vars are ignored.
"""

import argparse
import ssl
import sys
import urllib.error
import urllib.request

from app import config

# Keep in sync with app/readiness.py
READINESS_PATH = "/health/ready"


def probe(scheme: str, host: str, port: int, path: str, timeout: float) -> int:
    token = config.READINESS_TOKEN
    if not token:
        print("READINESS_TOKEN is not set", file=sys.stderr)
        return 1

    request = urllib.request.Request(
        f"{scheme}://{host}:{port}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as e:
        print(f"readiness probe got status {e.code}: {e.read()!r}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"readiness probe failed: {e}", file=sys.stderr)
        return 1
    if status != 200:
        print(f"readiness probe got status {status}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scheme", choices=["http", "https"], default="http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--path", default=READINESS_PATH)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    return probe(args.scheme, args.host, args.port, args.path, args.timeout)


if __name__ == "__main__":
    sys.exit(main())

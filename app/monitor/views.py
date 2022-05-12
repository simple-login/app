from app.build_info import SHA1
from app.monitor.base import monitor_bp


@monitor_bp.route("/git")
def git_sha1():
    return SHA1


@monitor_bp.route("/live")
def live():
    return "live"


@monitor_bp.route("/exception")
def test_exception():
    raise Exception("to make sure sentry works")
    return "never reach here"

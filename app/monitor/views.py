from flask_login import login_required

from app.build_info import SHA1, VERSION
from app.monitor.base import monitor_bp


@monitor_bp.route("/git")
@login_required
def git_sha1():
    return SHA1


@monitor_bp.route("/version")
@login_required
def version():
    return VERSION


@monitor_bp.route("/live")
def live():
    return "live"


@monitor_bp.route("/exception")
@login_required
def test_exception():
    raise Exception("to make sure sentry works")
    return "never reach here"

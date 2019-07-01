import subprocess

from app.monitor.base import monitor_bp

SHA1 = subprocess.getoutput("git rev-parse HEAD")


@monitor_bp.route("/git")
def git_sha1():
    return SHA1


@monitor_bp.route("/exception")
def test_exception():
    raise Exception("to make sure sentry works")
    return "never reach here"

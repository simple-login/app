from app.build_info import VERSION
import newrelic.agent


def send_version_event(service: str):
    newrelic.agent.record_custom_event(
        "ServiceVersion", {"service": service, "version": VERSION}
    )

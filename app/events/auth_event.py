import newrelic.agent

from app.models import EnumE


class LoginEvent:
    class ActionType(EnumE):
        success = 0
        failed = 1
        disabled_login = 2
        not_activated = 3

    class Source(EnumE):
        web = 0
        api = 1

    def __init__(self, action: ActionType, source: Source = Source.web):
        self.action = action
        self.source = source

    def send(self):
        newrelic.agent.record_custom_event(
            "LoginEvent", {"action": self.action.name, "source": self.source.name}
        )


class RegisterEvent:
    class ActionType(EnumE):
        success = 0
        failed = 1
        catpcha_failed = 2
        email_in_use = 3
        invalid_email = 4

    class Source(EnumE):
        web = 0
        api = 1

    def __init__(self, action: ActionType, source: Source = Source.web):
        self.action = action
        self.source = source

    def send(self):
        newrelic.agent.record_custom_event(
            "RegisterEvent", {"action": self.action.name, "source": self.source.name}
        )

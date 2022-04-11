import newrelic

from app.models import EnumE


class LoginEvent:
    class ActionType(EnumE):
        success = 0
        failed = 1
        disabled_login = 2
        not_activated = 3

    def __init__(self, action: ActionType):
        self.action = action

    def send(self):
        newrelic.agent.record_custom_event("LoginEvent", {"action": self.action})


class RegisterEvent:
    class ActionType(EnumE):
        success = 0
        catpcha_failed = 1
        email_in_use = 2
        invalid_email = 3

    def __init__(self, action: ActionType):
        self.action = action

    def send(self):
        newrelic.agent.record_custom_event("RegisterEvent", {"action": self.action})

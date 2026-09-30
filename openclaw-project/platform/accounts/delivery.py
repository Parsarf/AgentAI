from django.core.mail.backends.base import BaseEmailBackend
class DeliveryUnavailable(Exception):
    pass
class DisabledEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise DeliveryUnavailable('Mail delivery is not configured')

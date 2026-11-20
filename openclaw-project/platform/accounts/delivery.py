from django.core.mail.backends.base import BaseEmailBackend
class DeliveryUnavailable(Exception):
    pass
class DisabledEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise DeliveryUnavailable('Mail delivery is not configured')


RESERVED_SUFFIXES = ('.test', '.example', '.invalid', '.localhost')          # RFC 2606 and RFC 6761: names that can never receive mail
RESERVED_DOMAINS = ('example.com', 'example.net', 'example.org')


def deliverable(address) -> bool:
    """Can mail to this address ever arrive? An address at a reserved name (the disposable accounts of the live proofs use @invalid.test) is never sent to: the message
    could only bounce back to Lumina's own sending mailbox."""
    local, at, domain = str(address or '').rpartition('@')
    domain = domain.strip().lower().rstrip('.')
    if not at or not local:
        return False
    return bool(domain) and not ('.' + domain).endswith(RESERVED_SUFFIXES) and domain not in RESERVED_DOMAINS

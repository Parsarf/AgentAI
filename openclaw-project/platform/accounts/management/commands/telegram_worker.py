"""Host-side Telegram outbox drain; refuses without configured authorization."""
import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from accounts import wiring
class Command(BaseCommand):
    help='Drain pending Telegram replies; the bot token stays in ingress configuration.'
    def add_arguments(self,p):p.add_argument('--check',action='store_true');p.add_argument('--drain',action='store_true')
    def handle(self,*args,**o):
        if not o['check'] and not o['drain']:raise CommandError('Use --check or --drain')
        store=wiring.store()
        service=wiring.telegram_service(store)
        if o['check']:
            with store.connect() as con:
                counts=dict(con.execute("SELECT state,count(*) FROM telegram_outbox GROUP BY state").fetchall())
            self.stdout.write(json.dumps({'outbox':counts,'telegram_enabled':settings.TELEGRAM_ENABLED}))
            return
        if not settings.TELEGRAM_ENABLED:
            raise CommandError('Telegram ingress is not configured; pending replies were not sent')
        sent=service.drain()
        self.stdout.write(json.dumps({'drained':sent}))

"""Host-side Telegram outbox drain; refuses without configured authorization."""
import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from agentai_platform.telegram import TelegramService, TelegramBotApi
from agentai_platform.request_queue import RequestQueue
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService
from accounts.lifecycle import AccountStore
class Command(BaseCommand):
    help='Drain pending Telegram replies; the bot token stays in ingress configuration.'
    def add_arguments(self,p):p.add_argument('--check',action='store_true');p.add_argument('--drain',action='store_true')
    def handle(self,*args,**o):
        if not o['check'] and not o['drain']:raise CommandError('Use --check or --drain')
        store=AccountStore(connection.settings_dict['NAME'])
        service=TelegramService(store,chat=ChatService(store,queue=RequestQueue(store),ledger=BudgetLedger(store)),
            transport=TelegramBotApi(settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_ENABLED else None,
            bot_username=settings.TELEGRAM_BOT_USERNAME)
        if o['check']:
            with store.connect() as con:
                counts=dict(con.execute("SELECT state,count(*) FROM telegram_outbox GROUP BY state").fetchall())
            self.stdout.write(json.dumps({'outbox':counts,'telegram_enabled':settings.TELEGRAM_ENABLED}))
            return
        if not settings.TELEGRAM_ENABLED:
            raise CommandError('Telegram ingress is not configured; pending replies were not sent')
        sent=service.drain()
        self.stdout.write(json.dumps({'drained':sent}))

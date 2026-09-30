"""Prepared queue worker entry point; no native or fixture driver exposed."""
import json
from django.db import connection
from django.core.management.base import BaseCommand,CommandError
from accounts.requests import queue
from agentai_platform.request_queue import DisabledRequestDriver
from agentai_platform.capacity import CapacityResult
from agentai_platform.adapters import CapabilityUnavailable
class Command(BaseCommand):
    help='Inspect serial request queue; native execution stays disabled until host adapter is connected.'
    def add_arguments(self,p):p.add_argument('--check',action='store_true');p.add_argument('--once',action='store_true')
    def handle(self,*args,**o):
        if not o['check'] and not o['once']:raise CommandError('Use --check or --once')
        if o['check']:
            with connection.cursor() as c:
                c.execute('SELECT state,count(*) FROM customer_requests GROUP BY state');counts=dict(c.fetchall())
                c.execute('SELECT count(*) FROM request_slot');occupied=c.fetchone()[0]
            self.stdout.write(json.dumps({'requests':counts,'global_slot_occupied':bool(occupied),'execution_ready':False}))
            return
        try:queue().run_once(DisabledRequestDriver(),owner='request-worker',capacity=CapacityResult(None,None,None,None,0,('runtime_unverified',)))
        except CapabilityUnavailable:raise CommandError('Native worker adapter is not connected; queued requests were not executed') from None

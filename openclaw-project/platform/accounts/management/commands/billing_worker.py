"""Host-side billing worker: apply stored webhook events, sweep time-based access, reconcile.

Processes the inbox (leases, backoff, dead-letter), moves grace/period ends without needing
a webhook, and with --reconcile compares each subscription with the provider's canonical state.
Prints counts only; no account, customer or key detail is written to the journal.
"""
import json
from django.core.management.base import BaseCommand, CommandError
from agentai_platform.billing import BillingNotConfigured
from accounts.billing import service


class Command(BaseCommand):
    help = 'Process the billing webhook inbox and sweep entitlements.'

    def add_arguments(self, parser):
        parser.add_argument('--reconcile', action='store_true')
        parser.add_argument('--check', action='store_true')

    def handle(self, *args, **options):
        svc = service()
        if options['check']:
            with svc.store.connect() as con:
                inbox = dict(con.execute('SELECT status,count(*) FROM billing_inbox GROUP BY status').fetchall())
            self.stdout.write(json.dumps({'inbox': inbox, 'webhook_configured': bool(svc.secrets), 'provider_configured': svc.api is not None}))
            return
        if svc.api is None:
            raise CommandError('Billing provider is not configured; nothing was processed')
        try:
            report = svc.process(50)
            report['swept'] = svc.sweep()
            if options['reconcile']:
                report['reconcile'] = svc.reconcile()
        except BillingNotConfigured as exc:
            raise CommandError(str(exc))
        self.stdout.write(json.dumps(report, sort_keys=True))

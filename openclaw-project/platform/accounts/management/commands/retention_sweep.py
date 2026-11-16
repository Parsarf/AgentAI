"""The one retention sweeper (roadmap #18): enforces every row of the retention table that is the sweeper's (agentai_platform/retention.py), then the sign-in and
security records the account app owns (retention_accounts). Run by a daily timer; it prints counts only.

Never exposed as an HTTP route. `--dry-run` shows the table and deletes nothing."""
import json

from django.core.management import call_command
from django.core.management.base import BaseCommand

from agentai_platform import retention
from accounts import wiring


class Command(BaseCommand):
    help = 'Enforce the retention table: delete what is older than its row allows.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if options['dry_run']:
            self.stdout.write(json.dumps({'rules': {r.key: {'days': r.days, 'by': r.by} for r in retention.RULES}}, sort_keys=True))
            return
        done = retention.sweep(wiring.store(), storage=wiring.file_store())
        call_command('retention_accounts', stdout=self.stdout)
        self.stdout.write(json.dumps({'removed': done}, sort_keys=True))

"""Move exports, deletions and offboardings forward (roadmap #19 to #21). Run by a timer every minute; each job carries on from its last checkpoint. Prints counts only."""
import json

from django.core.management.base import BaseCommand

from accounts import wiring


class Command(BaseCommand):
    help = 'Run one pass over the account jobs (export, deletion, offboarding).'

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(wiring.account_jobs().tick(), sort_keys=True))

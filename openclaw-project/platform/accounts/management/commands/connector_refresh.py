"""Keep connected services' tokens fresh and finish removing the tokens of connections that were ended (roadmap #16, #17). Run by a timer; it prints counts only."""
import json

from django.core.management.base import BaseCommand

from accounts import wiring


class Command(BaseCommand):
    help = 'Refresh connector tokens that are about to end, purge the tokens of removed connections, keep remote MCP OAuth connections fresh.'

    def handle(self, *args, **options):
        if not (wiring.switch_on('connectors_linking') or wiring.switch_on('synthetic_connector') or wiring.switch_on('account_self_service')):
            self.stdout.write(json.dumps({'idle': 'connected services are off'}))
            return
        self.stdout.write(json.dumps(wiring.connector_refresher().tick(), sort_keys=True))      # connection ids and outcomes are logged by the job itself; never a token

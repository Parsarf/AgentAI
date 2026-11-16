"""Keep the dashboard's copy of connected mail and calendars current (roadmap #D2). Run by a timer; it prints counts only, never anything from a mailbox."""
import json
import time

from django.core.management.base import BaseCommand

from accounts import wiring


class Command(BaseCommand):
    help = 'Sync connected mail and calendar accounts for the dashboard: follow connections and grants, then run what is due.'

    def add_arguments(self, parser):
        parser.add_argument('--seconds', type=int, default=45, help='keep running what is due for at most this long (a first fill takes several passes)')

    def handle(self, *args, **options):
        if not wiring.switch_on('mail_calendar_dashboard'):
            self.stdout.write(json.dumps({'idle': 'the mail and calendar dashboard is off'}))
            return
        sync = wiring.hub_services()[2]
        total, until = {'ran': 0, 'changed': 0, 'failed': 0}, time.monotonic() + max(1, options['seconds'])
        while True:
            report = sync.tick(limit=10)
            for key in total:
                total[key] += report[key]
            if report['ran'] == 0 or report['ran'] == report['failed'] or time.monotonic() >= until:
                break
        self.stdout.write(json.dumps(total, sort_keys=True))

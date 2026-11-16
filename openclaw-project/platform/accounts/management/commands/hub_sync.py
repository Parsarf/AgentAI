"""Keep the dashboard's copy of connected mail and calendars current (roadmap #D2). It prints counts only, never anything from a mailbox.

    manage.py hub_sync            one bounded pass (what is due now), then exit
    manage.py hub_sync --serve    run for good: the service. It asks each provider what changed every few seconds (one cheap call per mailbox), and works through a first
                                  fill page after page without pausing. This is what makes the Inbox and the Calendar live.
"""
import json
import time

from django.core.management.base import BaseCommand

from accounts import wiring


class Command(BaseCommand):
    help = 'Sync connected mail and calendar accounts for the dashboard: follow connections and grants, then run what is due.'

    def add_arguments(self, parser):
        parser.add_argument('--seconds', type=int, default=45, help='one pass: keep running what is due for at most this long')
        parser.add_argument('--serve', action='store_true', help='run for good (the service)')

    def handle(self, *args, **options):
        if options['serve']:
            return self.serve()
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

    def serve(self, *, sleep=time.sleep, rounds=None):
        """The service loop. One worker: a row left "running" by a worker that was stopped is taken back at the start instead of waiting out its lease."""
        from django.db import connection
        with connection.cursor() as c:
            c.execute("UPDATE hub_sync SET state='waiting',lease_epoch=NULL WHERE state='running'")
        done, last_said = 0, 0.0
        totals = {'ran': 0, 'changed': 0, 'failed': 0}
        while rounds is None or done < rounds:
            done += 1
            if not wiring.switch_on('mail_calendar_dashboard'):
                sleep(30)                                   # switched off: nothing is asked of any provider
                continue
            try:
                report = wiring.hub_services()[2].tick(limit=10)
            except Exception as error:                      # never let one bad pass end the service; say what kind it was, never its text
                self.stdout.write(json.dumps({'error': type(error).__name__})); self.stdout.flush()
                sleep(10)
                continue
            for key in totals:
                totals[key] += report[key]
            if (totals['changed'] or totals['failed']) and time.monotonic() - last_said >= 60:      # at most one line a minute, and only when something happened
                self.stdout.write(json.dumps(totals, sort_keys=True)); self.stdout.flush()
                totals, last_said = {'ran': 0, 'changed': 0, 'failed': 0}, time.monotonic()
            sleep(0.2 if report['ran'] and report['ran'] != report['failed'] else 2)

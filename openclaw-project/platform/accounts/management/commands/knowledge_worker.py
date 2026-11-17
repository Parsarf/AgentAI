"""Read the customer's sources into the knowledge index (roadmap Phase 4). It prints counts only, never anything from a document.

    manage.py knowledge_worker            one bounded pass (removals, new uploads, up to a few sources), then exit
    manage.py knowledge_worker --serve    run for good: the service. Removals finish within seconds; new and changed files are read in the order they arrived.
"""
import json
import time

from django.core.management.base import BaseCommand

from accounts import wiring


class Command(BaseCommand):
    help = 'Read customers\' files into the knowledge index, finish removals, notice deleted and changed files.'

    def add_arguments(self, parser):
        parser.add_argument('--serve', action='store_true', help='run for good (the service)')
        parser.add_argument('--limit', type=int, default=3, help='sources to read per pass')

    def _pass(self, service, limit):
        added = service.discover() if wiring.switch_on('customer_knowledge') else 0
        report = service.work_once(enabled=wiring.knowledge_on, limit=limit)
        return {'added': added, **report}

    def handle(self, *args, **options):
        if options['serve']:
            return self.serve(limit=max(1, min(options['limit'], 10)))
        service = wiring.knowledge_service()
        if service is None:
            self.stdout.write(json.dumps({'idle': 'the knowledge index is not installed on this host'}))
            return
        self.stdout.write(json.dumps(self._pass(service, max(1, min(options['limit'], 10))), sort_keys=True))

    def serve(self, *, limit=3, sleep=time.sleep, rounds=None):
        from django.db import connection
        with connection.cursor() as c:
            # One worker: a source left "working" by a worker that was stopped is read again at once instead of waiting out its lease.
            c.execute("UPDATE knowledge_sources SET state='queued',lease_owner=NULL,lease_until=NULL WHERE state='working' AND lease_owner='knowledge'")
        done, last_said, totals = 0, 0.0, {}
        while rounds is None or done < rounds:
            done += 1
            service = wiring.knowledge_service()
            if service is None:
                sleep(60)                                    # not installed (yet): nothing to do
                continue
            try:
                report = self._pass(service, limit)
            except Exception as error:                       # never let one bad pass end the service; say what kind it was, never its text
                self.stdout.write(json.dumps({'error': type(error).__name__})); self.stdout.flush()
                sleep(10)
                continue
            for key, value in report.items():
                totals[key] = totals.get(key, 0) + value
            if any(totals.values()) and time.monotonic() - last_said >= 60:
                self.stdout.write(json.dumps(totals, sort_keys=True)); self.stdout.flush()
                totals, last_said = {}, time.monotonic()
            if not (report.get('indexed') or report.get('failed') or report.get('waiting')):
                sleep(3)                                     # nothing was read: removals are still finished within seconds

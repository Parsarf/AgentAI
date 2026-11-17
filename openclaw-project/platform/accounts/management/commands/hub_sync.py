"""Keep the dashboard's copy of connected mail and calendars current (roadmap #D2). It prints counts only, never anything from a mailbox.

    manage.py hub_sync            one bounded pass (what is due now), then exit
    manage.py hub_sync --serve    run for good: the service. It asks each provider what changed every few seconds (one cheap call per mailbox), and works through a first
                                  fill page after page without pausing. This is what makes the Inbox and the Calendar live.

Memory (production, 2026-11-16: the service grew about 10 MB a minute and the kernel killed it at its 1 GB cap every hour or so). The service now builds its services
once instead of once per pass, says its size every ten minutes, and when it passes `AGENTAI_HUB_SYNC_RECYCLE_MB` (default 600) it finishes the pass and exits so systemd
starts a fresh one five seconds later (Restart=always): nothing is lost, every row carries its own checkpoint. `kill -USR1 <pid>` once starts tracing allocations, a second
time prints the code locations that grew most since (sizes and file:line only, never anything read).
"""
import gc
import json
import os
import signal
import time
import tracemalloc

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
            self.say({'idle': 'the mail and calendar dashboard is off'})
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

    def serve(self, *, sleep=time.sleep, rounds=None, size=None, recycle_mb=None, clock=time.monotonic):
        """The service loop. One worker: a row left "running" by a worker that was stopped is taken back at the start instead of waiting out its lease."""
        from django.db import connection
        with connection.cursor() as c:
            c.execute("UPDATE hub_sync SET state='waiting',lease_epoch=NULL WHERE state='running'")
        size = size or resident_mb
        recycle_mb = recycle_mb if recycle_mb is not None else _recycle_mb()
        self._watch_memory()
        done, last_said, last_size = 0, 0.0, clock()
        totals, services = {'ran': 0, 'changed': 0, 'failed': 0}, None
        while rounds is None or done < rounds:
            done += 1
            if not wiring.switch_on('mail_calendar_dashboard'):
                services = None
                sleep(30)                                   # switched off: nothing is asked of any provider
                continue
            try:
                services = services or wiring.hub_services()
                report = services[2].tick(limit=10)
            except Exception as error:                      # never let one bad pass end the service; say what kind it was, never its text
                services = None                             # and start the next pass from fresh services
                self.say({'error': type(error).__name__})
                sleep(10)
                continue
            for key in totals:
                totals[key] += report[key]
            if (totals['changed'] or totals['failed']) and clock() - last_said >= 60:      # at most one line a minute, and only when something happened
                self.say(totals)
                totals, last_said = {'ran': 0, 'changed': 0, 'failed': 0}, clock()
            if done % 200 == 0:
                gc.collect()
            mb = size()
            if mb is not None and clock() - last_size >= 600:
                self.say({'rss_mb': mb, 'passes': done})
                last_size = clock()
            if mb is not None and recycle_mb and mb >= recycle_mb:
                self.say({'recycle': True, 'rss_mb': mb, 'passes': done})      # systemd starts a fresh process; each row's checkpoint is in the database
                return 'recycle'
            sleep(0.2 if report['ran'] and report['ran'] != report['failed'] else 2)

    def say(self, what):
        self.stdout.write(json.dumps(what, sort_keys=True)); self.stdout.flush()

    def _watch_memory(self):
        if not hasattr(signal, 'SIGUSR1'):
            return
        state = {}

        def on_signal(_signum, _frame):
            if not tracemalloc.is_tracing():
                tracemalloc.start(10)
                state['since'] = tracemalloc.take_snapshot()
                self.say({'memory_trace': 'started'})
                return
            grown = tracemalloc.take_snapshot().compare_to(state['since'], 'lineno')[:15]
            for stat in grown:
                frame = stat.traceback[0]
                self.say({'grew_kb': stat.size_diff // 1024, 'blocks': stat.count_diff, 'at': f'{os.path.relpath(frame.filename)}:{frame.lineno}'})
            traced, _peak = tracemalloc.get_traced_memory()
            self.say({'traced_mb': traced // 1048576, 'rss_mb': resident_mb()})
        try:
            signal.signal(signal.SIGUSR1, on_signal)
        except ValueError:                                  # not the main thread (a test runner): no signal handler
            pass


def resident_mb():
    """This process's resident memory in MB (Linux), or None where /proc is not there."""
    try:
        with open('/proc/self/statm') as f:
            return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') // 1048576
    except (OSError, ValueError, IndexError):
        return None


def _recycle_mb():
    try:
        return max(0, int(os.environ.get('AGENTAI_HUB_SYNC_RECYCLE_MB', '600')))
    except ValueError:
        return 600

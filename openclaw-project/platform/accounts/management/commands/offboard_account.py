"""Operator command: close an account for a customer who asked by email (roadmap #21). The same flow as the customer's own button: stop the work, (optionally) export, end
every connection, cancel the subscription, wait out the cooling-off, delete, confirm by email with the deletion report.

    manage.py offboard_account --account <id> [--export] [--cooling-off-days N] [--status]

It only STARTS the job; the account-jobs timer moves it. `--status` prints where a job stands. Nothing is deleted before the cooling-off has passed."""
import json

from django.core.management.base import BaseCommand, CommandError

from agentai_platform.security import NotFound
from accounts import wiring


class Command(BaseCommand):
    help = 'Start (or show) the offboarding of one account.'

    def add_arguments(self, parser):
        parser.add_argument('--account', required=True)
        parser.add_argument('--export', action='store_true', help='make an export archive first')
        parser.add_argument('--cooling-off-days', type=int, default=None)
        parser.add_argument('--status', action='store_true')
        parser.add_argument('--operator', default='host')

    def handle(self, *args, **options):
        jobs = wiring.account_jobs()
        if options['status']:
            with wiring.store().connect() as con:
                rows = [dict(r) for r in con.execute("SELECT id,kind,state,waiting_for,not_before_epoch,steps_json FROM account_jobs WHERE account_id=? ORDER BY created_epoch DESC LIMIT 5", (options['account'],))]
            self.stdout.write(json.dumps([{**r, 'steps': [s['step'] for s in json.loads(r.pop('steps_json'))]} for r in rows], indent=1))
            return
        days = options['cooling_off_days']
        if days is not None and not 0 <= days <= 90:
            raise CommandError('the cooling-off is between 0 and 90 days')
        try:
            job = jobs.start_offboarding_by_operator(options['account'], options['operator'], cooling_off=None if days is None else days * 86400, export=options['export'])
        except NotFound:
            raise CommandError('no such account')
        self.stdout.write(json.dumps({'job': job, 'cooling_off_days': days if days is not None else jobs.cooling_off // 86400}))

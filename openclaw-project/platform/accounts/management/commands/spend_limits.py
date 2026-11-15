"""Owner tool: the default spending limits for every account that has not chosen its own (Lumina applies none unless you store one here).

  manage.py spend_limits show
  manage.py spend_limits set --task 5 --daily 15 --period 25     # dollars; leave one out for "no limit" on it
  manage.py spend_limits clear                                   # back to no default: no limit for anyone who has not chosen one

A customer's own choice in Settings > Usage always wins over this default, including their choice of "no limit".
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from agentai_platform import spend_limits
from accounts import wiring


class Command(BaseCommand):
    help = 'Show, set or clear the default spending limits for all accounts.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['show', 'set', 'clear'])
        for name in spend_limits.FIELDS:
            parser.add_argument('--' + name, default=None, help='dollars, e.g. 5 or 2.50')

    def handle(self, *args, **options):
        store = wiring.store()
        if options['action'] == 'set':
            chosen = {}
            for name in spend_limits.FIELDS:
                raw = options[name]
                try:
                    chosen[name] = None if raw is None else int(Decimal(raw) * 1_000_000)
                except Exception:
                    raise CommandError(f'--{name} must be a dollar amount')
            try:
                with store.transaction() as con:
                    spend_limits.put(con, spend_limits.ALL, chosen)
            except ValueError as error:
                raise CommandError(str(error))
        elif options['action'] == 'clear':
            with store.transaction() as con:
                spend_limits.clear(con, spend_limits.ALL)
        with store.connect() as con:
            default = spend_limits.own(con, spend_limits.ALL)
        if default is None:
            self.stdout.write('No default: an account has no spending limit unless its customer chose one.')
            return
        for name in spend_limits.FIELDS:
            value = default[name]
            self.stdout.write(f'{name}: ' + ('no limit' if value is None else f'${value / 1_000_000:.2f}'))

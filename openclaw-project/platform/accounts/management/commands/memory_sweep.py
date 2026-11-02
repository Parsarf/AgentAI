"""Long-term memory housekeeping (agentai_platform/longterm_memory.py). Run every few minutes from a timer, as the app user.

* Retries index deletions the Hindsight server could not confirm (an entry is hidden and blanked in Lumina at once; this closes the loop) and cleans up saves that never finished.
* `--erase-account <id>`: removes everything remembered for one account (its whole bank). Run it when an account is deleted.
* `--reindex-account <id>`: rebuilds one account's index from the ledger (after the index server was lost or replaced).
Prints counts only, never content."""
from django.core.management.base import BaseCommand, CommandError
from accounts import longterm
from agentai_platform.longterm_memory import MemoryError_


class Command(BaseCommand):
    help = 'Retry unconfirmed long-term memory deletions; optionally erase one account\'s memory.'

    def add_arguments(self, parser):
        parser.add_argument('--erase-account', default='')
        parser.add_argument('--reindex-account', default='')

    def handle(self, *args, **options):
        memory = longterm.build()
        if memory is None:
            self.stdout.write('long-term memory is not configured; nothing to do')
            return
        if options['erase_account']:
            try:
                memory.forget_all(options['erase_account'])
            except MemoryError_ as error:
                raise CommandError('erase did not finish; the entries are blanked and `memory_sweep` will retry: ' + str(error))
            self.stdout.write('erased')
            return
        if options['reindex_account']:
            try:
                self.stdout.write(f'reindexed {memory.reindex(options["reindex_account"])}')
            except MemoryError_ as error:
                raise CommandError('reindex did not finish: ' + str(error))
            return
        self.stdout.write(f'closed {memory.sweep()}')

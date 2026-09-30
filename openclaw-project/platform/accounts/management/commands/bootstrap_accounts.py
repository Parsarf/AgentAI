from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.conf import settings
from agentai_platform.store import Store
class Command(BaseCommand):
    help='Initialize private state and migrate accounts; creates no identities or listeners.'
    def handle(self,*args,**options):
        Store(settings.DATABASES['default']['NAME']).initialize()
        call_command('migrate',interactive=False,verbosity=options['verbosity'])

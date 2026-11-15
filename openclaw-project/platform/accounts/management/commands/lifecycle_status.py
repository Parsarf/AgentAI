"""Private queue diagnostics. No native dispatch, secret or target-path output."""
import json
from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help='Show lifecycle queue, cell-slot and running-request counts; does not start or stop any agent.'
    def handle(self,*args,**options):
        with connection.cursor() as c:
            c.execute('''SELECT o.state,count(*) FROM operations o JOIN lifecycle_details d
                ON d.account_id=o.account_id AND d.operation_id=o.id GROUP BY o.state''')
            counts=dict(c.fetchall())
            c.execute('SELECT state,count(*) FROM cell_slots GROUP BY state');cells=dict(c.fetchall())
            c.execute('SELECT count(*) FROM request_slots');running=c.fetchone()[0]
        self.stdout.write(json.dumps({'operations':counts,'slot':next(iter(sorted(cells)),'free'),'cells':cells,'running_requests':running,
                                     'native_driver':'disabled','customer_execution_enabled':False}))

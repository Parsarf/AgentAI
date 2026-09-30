"""Private queue diagnostics. No native dispatch, secret or target-path output."""
import json
from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help='Show lifecycle queue/global-slot counts; does not start or stop any agent.'
    def handle(self,*args,**options):
        with connection.cursor() as c:
            c.execute('''SELECT o.state,count(*) FROM operations o JOIN lifecycle_details d
                ON d.account_id=o.account_id AND d.operation_id=o.id GROUP BY o.state''')
            counts=dict(c.fetchall())
            c.execute('SELECT state FROM lifecycle_slot WHERE id=1');slot=c.fetchone()
        self.stdout.write(json.dumps({'operations':counts,'slot':slot[0] if slot else 'free',
                                     'native_driver':'disabled','customer_execution_enabled':False}))

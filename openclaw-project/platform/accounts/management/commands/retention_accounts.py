"""Restricted host maintenance, never exposed as an application HTTP route."""
import uuid
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import connection,transaction
from django.utils import timezone
from accounts.models import Audit, ActionToken, RateBucket, Tombstone, EmailJob
from django.contrib.sessions.models import Session
from accounts.services import audit
class Command(BaseCommand):
    help='Expire identity tokens/rate buckets and enforce 180-day audit / 90-day product chat projection retention.'
    def handle(self,*args,**o):
        now=timezone.now(); request=uuid.uuid4(); op=uuid.uuid4()
        with transaction.atomic():
            audit('host-maintenance',None,'retention','retention.run','pending',request,op)
            ActionToken.objects.filter(expires_at__lt=now).delete()
            RateBucket.objects.filter(expires_at__lt=now).delete()
            Session.objects.filter(expire_date__lt=now).delete()
            EmailJob.objects.filter(created_at__lt=now-timedelta(days=180)).delete()
            # Privileged host policy: temporarily lift only delete guards in this transaction.
            # SQLite transactional DDL restores guards on any failure. HTTP has no equivalent path.
            with connection.cursor() as c:
                c.execute('DROP TRIGGER identity_audit_no_delete')
                Audit.objects.filter(created_at__lt=now-timedelta(days=180)).delete()
                c.execute("CREATE TRIGGER identity_audit_no_delete BEFORE DELETE ON accounts_audit BEGIN SELECT RAISE(ABORT,'audit is append only'); END")
                c.execute('DROP TRIGGER audit_no_delete')
                c.execute('DELETE FROM audit_events WHERE created_at < %s',[(now-timedelta(days=180)).strftime('%Y-%m-%dT%H:%M:%SZ')])
                c.execute("CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit is append only'); END")
                c.execute('SELECT account_id,id FROM conversations WHERE created_at < %s',[(now-timedelta(days=90)).strftime('%Y-%m-%dT%H:%M:%SZ')])
                for account,obj in c.fetchall():
                    Tombstone.objects.get_or_create(account_id=account,object_id=obj,kind='conversation')
                    c.execute('DELETE FROM events WHERE account_id=%s AND task_id IN (SELECT id FROM tasks WHERE account_id=%s AND conversation_id=%s)',[account,account,obj])
                    # Preserve the private routing reference until native erasure can reconcile it in Phase 6.
            audit('host-maintenance',None,'retention','retention.run','completed',request,op)
        self.stdout.write('Retention maintenance completed; native runtime deletion awaits Phase 6 adapter')

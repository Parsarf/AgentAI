"""Bounded server worker. SMTP is opt-in; do not run for real people without authorization."""
import uuid
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction, connection
from django.utils import timezone
from datetime import timedelta
from accounts.models import EmailJob
from accounts.services import token_for, deliver, audit, customer_scope, Denied
class Command(BaseCommand):
    help='Deliver up to ten pending account instructions once; uncertain jobs never automatically retry.'
    def handle(self,*args,**o):
        if settings.EMAIL_BACKEND!='django.core.mail.backends.smtp.EmailBackend': raise CommandError('SMTP delivery is disabled')
        for _ in range(10):
            request=uuid.uuid4()
            with transaction.atomic():
                job=EmailJob.objects.filter(state='pending').order_by('id').first()
                if not job: break
                user=job.user; identity=user.identity
                if job.created_at<timezone.now()-timedelta(minutes=15):
                    job.state='failed'; job.save(update_fields=['state']); continue
                try:
                    if identity.role!='customer' or job.purpose not in ['recovery','onboarding']: raise Denied()
                    if job.purpose=='recovery': customer_scope(user,identity.epoch)
                    else:
                        if identity.verified: raise Denied()
                        with connection.cursor() as c:
                            c.execute("SELECT 1 FROM accounts a JOIN memberships m ON a.id=m.account_id WHERE a.id=%s AND a.status='active' AND m.actor_id=%s AND m.status='active' AND m.role='customer'",[identity.account_id,str(user.pk)])
                            if not c.fetchone(): raise Denied()
                    raw=token_for(user,job.purpose)
                except Denied:
                    job.state='failed'; job.save(update_fields=['state']); continue
                audit('mail-worker',identity.account_id,job.pk,'mail.claim','pending',request)
                job.state='running'; job.save(update_fields=['state'])
            sent=deliver(user,job.purpose,raw,request)
            with transaction.atomic():
                job.state='completed' if sent else 'uncertain'; job.save(update_fields=['state'])
                audit('mail-worker',identity.account_id,job.pk,'mail.claim',job.state,request)
        self.stdout.write('Bounded mail batch finished; crashed running jobs require reconciliation, never automatic retry')

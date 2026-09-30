from django.conf import settings
from django.db import models
import uuid

class Identity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    account_id = models.CharField(max_length=64, null=True)
    role = models.CharField(max_length=16, choices=[('customer','Customer'), ('operator','Internal operator'), ('service','Service')])
    verified = models.BooleanField(default=False)
    epoch = models.PositiveIntegerField(default=1)

class ActionToken(models.Model):
    digest = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=16, choices=[('onboarding','Onboarding'), ('recovery','Recovery')])
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    epoch = models.PositiveIntegerField()

class OperatorGrant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    account_id = models.CharField(max_length=64)
    action = models.CharField(max_length=32, choices=[('invite','Invite'), ('suspend','Suspend'), ('revoke','Revoke'), ('audit','Read audit')]+[('lifecycle_'+kind,'Lifecycle '+kind) for kind in ['create','start','stop','upgrade','backup','restore','delete']])
    expires_at = models.DateTimeField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user','account_id','action'], name='operator_scoped_grant')]

class Audit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation_id = models.UUIDField(default=uuid.uuid4, editable=False)
    actor = models.CharField(max_length=64)
    account_id = models.CharField(max_length=64, null=True)
    object_id = models.CharField(max_length=96)
    action = models.CharField(max_length=48)
    outcome = models.CharField(max_length=16, choices=[(x,x) for x in ['pending','completed','denied','failed','uncertain']])
    request_id = models.UUIDField()
    native_operation_id = models.CharField(max_length=96, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=['account_id','created_at'])]

class RateBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()

class Tombstone(models.Model):
    account_id = models.CharField(max_length=64)
    object_id = models.CharField(max_length=96)
    kind = models.CharField(max_length=32)
    erased_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['account_id','object_id','kind'], name='retention_object')]

class EmailJob(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=16, choices=[('onboarding','Onboarding'), ('recovery','Recovery')])
    state = models.CharField(max_length=16, default='pending', choices=[(x,x) for x in ['pending','running','completed','uncertain','failed']])
    created_at = models.DateTimeField(auto_now_add=True)
    # Contains no code, password or message text. Delivery generates a code in memory.

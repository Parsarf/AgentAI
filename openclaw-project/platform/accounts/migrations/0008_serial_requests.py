from importlib import import_module
from django.db import migrations
class Migration(migrations.Migration):
    dependencies=[('accounts','0007_budget_foundation')]
    operations=[migrations.RunPython(import_module('accounts.migrations.0000_foundation').adopt,migrations.RunPython.noop)]

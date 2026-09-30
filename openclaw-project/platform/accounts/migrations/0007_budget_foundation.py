"""Apply admission tables without changing prior schema migration bytes."""
from importlib import import_module
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [('accounts', '0006_lifecycle_grant_integrity')]
    operations = [migrations.RunPython(
        import_module('accounts.migrations.0000_foundation').adopt,
        migrations.RunPython.noop,
    )]

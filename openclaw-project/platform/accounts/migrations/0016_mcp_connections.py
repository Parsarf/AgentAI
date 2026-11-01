from importlib import import_module
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [('accounts', '0015_safety_access')]
    operations = [migrations.RunPython(import_module('accounts.migrations.0000_foundation').adopt, migrations.RunPython.noop)]

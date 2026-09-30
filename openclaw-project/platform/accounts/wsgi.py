import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from agentai_platform.store import Store
if not Store(settings.DATABASES['default']['NAME']).ready():
    raise RuntimeError('Foundation database is not ready; run explicit private bootstrap')
_executor=MigrationExecutor(connection)
if _executor.migration_plan(_executor.loader.graph.leaf_nodes()) or set(_executor.loader.applied_migrations)-set(_executor.loader.disk_migrations):
    raise RuntimeError('Account schema is missing migrations or is newer than this release')

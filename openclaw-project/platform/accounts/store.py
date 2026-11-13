"""The web app's database handle for the platform services.

`agentai_platform` services are written against `Store` (plain sqlite3, `?` placeholders, their own connection). Inside Django the same services must run on
DJANGO'S connection instead, so their writes join the request's transaction (the audit row and the effect commit or roll back together) and the test database
is the one they see. `AccountStore` is that adapter; nothing else about a service changes.

Build one with `accounts.wiring.store()`; do not construct it in a view.
"""
from contextlib import contextmanager
import sqlite3
from django.db import connection, transaction
from agentai_platform.store import Store


class Queries:
    def __init__(self, cursor): self.cursor=cursor
    def execute(self, sql, params=()):
        self.cursor.execute(sql.replace('?', '%s'),params)
        return self.cursor


class AccountStore(Store):
    @contextmanager
    def connect(self):
        with connection.cursor() as cursor:
            cursor.cursor.row_factory=sqlite3.Row
            yield Queries(cursor)
    @contextmanager
    def transaction(self):
        with transaction.atomic():
            with self.connect() as con: yield con

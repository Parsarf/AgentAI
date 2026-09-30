"""Adopt the checksummed Phase 2 schema without editing its migration."""
import hashlib
import sqlite3
from pathlib import Path
from django.db import migrations

def adopt(apps, schema_editor):
    c=schema_editor.connection.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
    files=sorted((Path(__file__).resolve().parents[2]/'migrations').glob('*.sql'))
    c.execute('SELECT version,checksum FROM schema_migrations'); applied=dict(c.fetchall())
    if set(applied)-{f.name for f in files}: raise RuntimeError('Unknown foundation schema')
    for file in files:
        digest=hashlib.sha256(file.read_bytes()).hexdigest()
        if file.name in applied:
            if applied[file.name]!=digest: raise RuntimeError('Foundation checksum mismatch')
            continue
        buf=''
        for line in file.read_text().splitlines(keepends=True):
            buf+=line
            if sqlite3.complete_statement(buf): c.execute(buf); buf=''
        if buf.strip(): raise RuntimeError('Incomplete migration')
        c.execute('INSERT INTO schema_migrations(version,checksum) VALUES (%s,%s)',[file.name,digest])

class Migration(migrations.Migration):
    initial=True
    dependencies=[]
    operations=[migrations.RunPython(adopt,migrations.RunPython.noop)]

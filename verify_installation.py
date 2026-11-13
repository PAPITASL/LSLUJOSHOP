"""Read-only data comparison. Runs only against the isolated recovered cluster."""
import json
import os
from pathlib import Path
import sys

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.desktop_settings'
import django
django.setup()
from recovery import inventory, database_metadata
from django.db import connections

expected = json.loads(Path(sys.argv[1]).read_text('utf-8'))
actual = inventory()
if actual != expected:
    raise RuntimeError('Los datos restaurados no coinciden con el respaldo: ' +
                       str([k for k in expected if expected[k] != actual.get(k)]))
if len(sys.argv) > 2:
    metadata = json.loads(Path(sys.argv[2]).read_text('utf-8'))
    if database_metadata() != metadata:
        raise RuntimeError('La configuracion regional de PostgreSQL no coincide con el respaldo.')
connections.close_all()
print('Todas las tablas y sus contenidos coinciden con el respaldo.')

"""Isolated database for tests; never uses the shop's PostgreSQL database."""
from .settings import *

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
MIGRATION_MODULES = {"gestion": None}

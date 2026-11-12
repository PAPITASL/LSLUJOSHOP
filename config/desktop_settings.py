"""Configuración exclusiva de la aplicación local de escritorio."""
from .settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"

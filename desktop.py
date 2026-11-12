"""Abre LujoShop como aplicación local, conservando su base PostgreSQL."""
import logging
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parent


def main():
    os.chdir(ROOT)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LujoShop.Desktop")
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.desktop_settings"
    import django
    import webview
    from django.core.wsgi import get_wsgi_application
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from waitress import create_server
    from whitenoise import WhiteNoise

    django.setup()
    # No crear ni migrar datos de forma silenciosa durante el arranque.
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise RuntimeError("Hay migraciones pendientes. Ejecuta manage.py migrate antes de abrir LujoShop.")
    connection.close()

    application = WhiteNoise(get_wsgi_application())
    application.add_files(str(ROOT / "static"), prefix="static/")
    from django.contrib import admin
    application.add_files(str(Path(admin.__file__).parent / "static"), prefix="static/")
    server = create_server(application, host="127.0.0.1", port=0, threads=4)
    thread = threading.Thread(target=server.run, name="lujoshop-server", daemon=True)
    thread.start()
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(
            "LujoShop", f"http://127.0.0.1:{server.effective_port}/",
            width=1360, height=900, min_size=(1000, 650),
        )
        webview.start(
            gui="edgechromium", private_mode=True,
            icon=str(ROOT / "static" / "img" / "lujoshop.ico"),
        )
    finally:
        server.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import ctypes
        import tempfile
        log = Path(tempfile.gettempdir()) / "LujoShop-error.log"
        logging.basicConfig(filename=log, level=logging.ERROR, encoding="utf-8")
        logging.exception("No fue posible iniciar LujoShop")
        ctypes.windll.user32.MessageBoxW(
            0,
            f"No fue posible iniciar LujoShop.\n\nComprueba que PostgreSQL esté iniciado.\n"
            f"{exc}\n\nDetalle técnico: {log}",
            "LujoShop", 0x10,
        )
        sys.exit(1)

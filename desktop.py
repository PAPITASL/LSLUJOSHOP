"""Abre LujoShop como aplicación local, conservando su base PostgreSQL."""
import logging
import os
from pathlib import Path
import sys
import threading
from local_runtime import exclusive, database

ROOT = Path(__file__).resolve().parent


def main():
    sys.argv[0] = str(ROOT / 'desktop.py')
    os.chdir(ROOT)
    if (ROOT / 'installation.json').exists() and not (ROOT / 'RESTAURACION-COMPLETA.txt').exists():
        raise RuntimeError('La restauracion no termino correctamente. Repite la recuperacion en otra carpeta nueva.')
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
        window = webview.create_window(
            "LujoShop", f"http://127.0.0.1:{server.effective_port}/",
            width=1360, height=900, min_size=(1000, 650),
        )
        loaded = threading.Event()
        closed = threading.Event()
        window.events.loaded += loaded.set
        def on_closed():
            closed.set()
            loaded.set()
        window.events.closed += on_closed
        startup_errors = []
        def check_startup():
            from urllib.request import urlopen
            try:
                if not loaded.wait(60):
                    raise RuntimeError('La ventana no termino de cargar en 60 segundos.')
                if closed.is_set():
                    return
                if '--smoke-test' not in sys.argv:
                    return
                with urlopen(f"http://127.0.0.1:{server.effective_port}/cuentas/login/", timeout=10) as response:
                    assert response.status == 200
                (ROOT / 'window-smoke-ok.txt').write_text(str(server.effective_port), 'utf-8')
            except Exception as error:
                startup_errors.append(error)
            finally:
                if startup_errors or '--smoke-test' in sys.argv:
                    window.destroy()

        webview.start(
            check_startup,
            gui="edgechromium", private_mode=True,
            icon=str(ROOT / "static" / "img" / "lujoshop.ico"),
        )
        if startup_errors:
            raise startup_errors[0]
    finally:
        server.close()
        thread.join(timeout=10)


if __name__ == "__main__":
    try:
        with exclusive(), database():
            main()
    except Exception as exc:
        import ctypes
        import tempfile
        log = Path(tempfile.gettempdir()) / "LujoShop-error.log"
        logging.basicConfig(filename=log, level=logging.ERROR, encoding="utf-8")
        logging.exception("No fue posible iniciar LujoShop")
        if '--smoke-test' in sys.argv:
            print(f'{exc}\nRegistro: {log}', file=sys.stderr)
            sys.exit(1)
        ctypes.windll.user32.MessageBoxW(
            0,
            f"No fue posible iniciar LujoShop.\n\nRevisa el detalle y la guia RECUPERACION.md.\n"
            f"{exc}\n\nDetalle técnico: {log}",
            "LujoShop", 0x10,
        )
        sys.exit(1)

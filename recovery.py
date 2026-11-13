"""Offline logical PostgreSQL backup and independent recovery. No source DB writes."""
import sys
sys.dont_write_bytecode = True
import argparse
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor

from local_runtime import ROOT, database, exclusive, pg_home, run, shortcut


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(root):
    paths = [p for p in root.rglob('*') if p.is_file() and p != root / 'SHA256.json']
    with ThreadPoolExecutor(max_workers=8) as pool:
        files = dict(zip((p.relative_to(root).as_posix() for p in paths), pool.map(digest, paths)))
    (root / 'SHA256.json').write_text(json.dumps(files, indent=2), 'utf-8')


def verify(root):
    expected = json.loads((root / 'SHA256.json').read_text('utf-8'))
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p != root / 'SHA256.json'}
    if actual != set(expected):
        raise RuntimeError('El respaldo tiene archivos faltantes o adicionales. Extrae el ZIP en una carpeta vacia.')
    def check(item):
        name, checksum = item
        if digest(root / name) != checksum:
            raise RuntimeError(f'Archivo alterado o incompleto: {name}')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check, expected.items()))


def db_settings():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.desktop_settings'
    import django
    django.setup()
    from django.conf import settings
    return settings.DATABASES['default']


def inventory():
    from django.apps import apps
    from django.db import connection
    result = {}
    with connection.cursor() as cur:
        for table in sorted(connection.introspection.table_names()):
            cur.execute('SELECT * FROM ' + connection.ops.quote_name(table))
            rows = sorted(json.dumps(row, default=str, ensure_ascii=False) for row in cur.fetchall())
            result[table] = {'count': len(rows), 'sha256': hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
    return result


def database_metadata():
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute('SELECT pg_encoding_to_char(encoding), datcollate, datctype, datlocprovider, '
                    'datlocale FROM pg_database WHERE datname=current_database()')
        return dict(zip(['encoding', 'collation', 'ctype', 'provider', 'locale'], cur.fetchone()))


def creation_options(metadata):
    if not metadata:
        return []  # Compatibility with the first local verification package.
    provider = {'c': 'libc', 'i': 'icu', 'b': 'builtin'}[metadata['provider']]
    args = ['--template=template0', '--encoding=' + metadata['encoding'],
            '--locale-provider=' + provider, '--lc-collate=' + metadata['collation'],
            '--lc-ctype=' + metadata['ctype']]
    if provider == 'icu':
        args += ['--icu-locale=' + metadata['locale']]
    elif provider == 'builtin':
        args += ['--builtin-locale=' + metadata['locale']]
    return args


def backup(output):
    if (ROOT / 'installation.json').exists() and not (ROOT / 'RESTAURACION-COMPLETA.txt').exists():
        raise RuntimeError('Esta instalacion no termino de restaurarse; no se creara un respaldo incompleto.')
    print('1/5 Creando instantanea y respaldo PostgreSQL...', flush=True)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with exclusive(), database(), tempfile.TemporaryDirectory(prefix='lujoshop-backup-') as tmp:
        stage = Path(tmp) / 'LujoShop-respaldo'
        app = stage / 'app'
        stage.mkdir()
        cfg = db_settings()
        from django.db import connection
        # Match dump and audit to the SAME PostgreSQL snapshot, including concurrent shared-service writes.
        connection.set_autocommit(False)
        try:
            with connection.cursor() as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                cur.execute('SELECT pg_export_snapshot()')
                snapshot = cur.fetchone()[0]
            audit = inventory()
            metadata = database_metadata()
            env = os.environ.copy()
            env['PGPASSWORD'] = cfg['PASSWORD'] or ''
            run([pg_home() / 'bin' / 'pg_dump.exe', '-h', cfg['HOST'], '-p', cfg['PORT'],
                 '-U', cfg['USER'], '-d', cfg['NAME'], '--format=custom', '--no-owner',
                 '--snapshot=' + snapshot, '--file', stage / 'database.dump'], env=env)
        finally:
            connection.rollback()
            connection.set_autocommit(True)
            connection.close()
        (stage / 'database-audit.json').write_text(json.dumps(audit, indent=2), 'utf-8')
        (stage / 'database-settings.json').write_text(json.dumps(metadata, indent=2), 'utf-8')
        print('2/5 Copiando aplicacion y herramientas para uso sin internet...', flush=True)
        excluded = {'.git', '.vscode', 'venv', '.venv', '__pycache__', 'runtime', 'local-data',
                    'backups', 'restoration-tests', '.desktop.lock', 'installation.json', 'logs',
                    'window-smoke-ok.txt', 'SMOKE-RESULTS.json', 'RESTAURACION-COMPLETA.txt',
                    'RESTAURACION-FALLIDA.txt'}
        def ignore(directory, names):
            return [n for n in names if n in excluded or n.endswith(('.pyc', '.zip', '.partial'))]
        shutil.copytree(ROOT, app, ignore=ignore)
        runtime = app / 'runtime'
        runtime.mkdir(exist_ok=True)
        if (ROOT / 'runtime' / 'python').exists():
            shutil.copytree(ROOT / 'runtime' / 'python', runtime / 'python',
                            ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copytree(Path(sys.base_prefix), runtime / 'python',
                            ignore=shutil.ignore_patterns('__pycache__', 'site-packages', 'Doc', 'Scripts', 'test', 'tests', 'idlelib', 'turtledemo'))
            import site
            shutil.copytree(Path(site.getsitepackages()[-1]), runtime / 'python' / 'Lib' / 'site-packages',
                            ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(pg_home(), runtime / 'postgres',
                        ignore=shutil.ignore_patterns('data', 'pgAdmin 4', 'installer', 'include', 'doc',
                                                     'uninstall*', 'scripts'))
        # A backup does not need the original shared-service password or any installation credentials.
        from django.conf import settings
        (app / '.env').write_text('SECRET_KEY=' + settings.SECRET_KEY + '\n', 'utf-8')
        shutil.copy2(ROOT / 'Instalar y restaurar.cmd', stage)
        shutil.copy2(ROOT / 'Instalar requisitos.cmd', stage)
        shutil.copy2(ROOT / 'RECUPERACION.md', stage)
        print('3/5 Calculando y comprobando SHA256 de todos los archivos...', flush=True)
        manifest(stage)
        verify(stage)
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        target = output / f'LujoShop-respaldo-{stamp}.zip'
        partial = target.with_suffix('.partial')
        try:
            print('4/5 Creando ZIP; puede tardar varios minutos...', flush=True)
            with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
                for path in stage.rglob('*'):
                    if path.is_file():
                        archive.write(path, path.relative_to(stage))
            with zipfile.ZipFile(partial) as archive:
                if archive.testzip():
                    raise RuntimeError('El ZIP no supera la comprobacion CRC.')
            partial.rename(target)
            target.with_suffix('.zip.sha256').write_text(digest(target) + '  ' + target.name + '\n', 'ascii')
            print('5/5 ZIP verificado. Respaldo completo.', flush=True)
        finally:
            partial.unlink(missing_ok=True)
    return target


def restore(source, target, create_shortcut=True):
    print('Verificando SHA256 de todos los archivos...', flush=True)
    source, target = Path(source).resolve(), Path(target).resolve()
    if target == source or source in target.parents:
        raise RuntimeError('Elige un destino fuera de la carpeta extraida del respaldo; la instalacion debe ser independiente.')
    if target.exists():
        raise RuntimeError('La carpeta de destino ya existe. Elige un nombre nuevo; no se sobrescribira nada.')
    verify(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / 'app', target)
    try:
        password = secrets.token_urlsafe(32)
        cfg = {'database': 'lujoshop', 'user': 'lujoshop', 'password': password}
        (target / 'installation.json').write_text(json.dumps(cfg), 'utf-8')
        data = target / 'local-data'
        data.mkdir()
        pwfile = data / 'init-password'
        pwfile.write_text(password, 'utf-8')
        pg = pg_home(target) / 'bin'
        try:
            run([pg / 'initdb.exe', '-D', data / 'postgres', '-U', cfg['user'],
                 '--pwfile', pwfile, '--auth-host=scram-sha-256', '--auth-local=scram-sha-256',
                 '--encoding=UTF8', '--locale=C'])
        finally:
            pwfile.unlink(missing_ok=True)
        with database(target):
            print('Restaurando PostgreSQL en una base privada nueva...', flush=True)
            env = os.environ.copy()
            env['PGPASSWORD'] = password
            args = ['-h', '127.0.0.1', '-p', env['DB_PORT'], '-U', cfg['user']]
            settings_file = source / 'database-settings.json'
            metadata = json.loads(settings_file.read_text('utf-8')) if settings_file.exists() else None
            run([pg / 'createdb.exe', *args, *creation_options(metadata), cfg['database']], env=env)
            run([pg / 'pg_restore.exe', *args, '-d', cfg['database'], '--no-owner', '--no-acl',
                 '--exit-on-error', '--single-transaction', source / 'database.dump'], env=env)
            run([target / 'runtime' / 'python' / 'python.exe', '-B', target / 'verify_installation.py',
                 source / 'database-audit.json', *([settings_file] if metadata else [])], env=env, cwd=target)
            print('Todas las tablas coinciden con el respaldo.', flush=True)
        if create_shortcut:
            shortcut(target)
        (target / 'RESTAURACION-COMPLETA.txt').write_text(
            'Integridad SHA256, restauracion PostgreSQL y comparacion de todas las tablas correctas.\n', 'utf-8')
    except Exception:
        (target / 'RESTAURACION-FALLIDA.txt').write_text('No usar esta instalacion. Consulte el registro del respaldo.\n', 'utf-8')
        raise
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'restore', 'shortcut'])
    parser.add_argument('--output')
    parser.add_argument('--source')
    parser.add_argument('--target')
    parser.add_argument('--no-shortcut', action='store_true')
    args = parser.parse_args()
    if args.action == 'backup':
        return backup(args.output or ROOT / 'backups')
    if args.action == 'shortcut':
        shortcut()
        return 'Acceso directo creado en el escritorio.'
    source = Path(args.source) if args.source else ROOT.parent
    target = args.target
    if not target:
        import tkinter as tk
        from tkinter import filedialog
        tk.Tk().withdraw()
        parent = filedialog.askdirectory(title='Elige donde crear una NUEVA carpeta LujoShop')
        if not parent:
            return 'Restauracion cancelada.'
        target = Path(parent) / ('LujoShop-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    return restore(source, target, not args.no_shortcut)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    try:
        print(f'Proceso terminado correctamente.\n{main()}', flush=True)
    except Exception as exc:
        log = Path(tempfile.gettempdir()) / 'LujoShop-recuperacion-error.log'
        logging.basicConfig(filename=log, level=logging.ERROR, encoding='utf-8')
        logging.exception('Respaldo/restauracion fallido')
        print(f'ERROR: {exc}\nRegistro: {log}', flush=True)
        sys.exit(1)

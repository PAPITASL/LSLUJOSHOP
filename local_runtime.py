"""Lifecycle shared by desktop, backup and isolated restoration (Windows)."""
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def run(args, **kwargs):
    # PostgreSQL inherits handles when detaching on Windows. A pipe would keep
    # communicate() waiting until the SERVER exits, even after pg_ctl has finished.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run([str(a) for a in args], creationflags=subprocess.CREATE_NO_WINDOW,
                                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, **kwargs)
        output.seek(0)
        message = output.read().decode('utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name}: {message}')
    return message


@contextlib.contextmanager
def exclusive(root=ROOT):
    import msvcrt
    handle = open(root / '.desktop.lock', 'a+b')
    if (root / '.desktop.lock').stat().st_size == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise RuntimeError('Cierra LujoShop y cualquier respaldo/restauracion en curso antes de continuar.')
    try:
        yield
    finally:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def pg_home(root=ROOT):
    bundled = root / 'runtime' / 'postgres'
    if bundled.exists():
        return bundled
    candidates = sorted(Path('C:/Program Files/PostgreSQL').glob('*/bin/pg_dump.exe'), reverse=True)
    if not candidates:
        raise RuntimeError('No se encuentran las herramientas PostgreSQL para crear el respaldo.')
    return candidates[0].parent.parent


@contextlib.contextmanager
def database(root=ROOT):
    config = root / 'installation.json'
    if not config.exists():
        yield  # Original installation uses the existing shared service; never stop it.
        return
    cfg = json.loads(config.read_text('utf-8'))
    data = root / 'local-data' / 'postgres'
    pg = pg_home(root) / 'bin' / 'pg_ctl.exe'
    if run_status(pg, data):
        raise RuntimeError('La base privada ya esta en uso. Cierra la otra instancia; no se detendra un proceso ajeno.')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {'DB_HOST': '127.0.0.1', 'DB_PORT': str(port), 'DB_NAME': cfg['database'],
           'DB_USER': cfg['user'], 'DB_PASSWORD': cfg['password']}
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    started = False
    try:
        run([pg, '-D', data, '-l', root / 'local-data' / 'postgres.log',
             '-o', f'-h 127.0.0.1 -p {port}', '-w', '-t', '40', 'start'])
        started = True
        yield
    finally:
        if started or run_status(pg, data):
            run([pg, '-D', data, '-m', 'fast', '-w', '-t', '40', 'stop'])
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_status(pg, data):
    result = subprocess.run([str(pg), '-D', str(data), 'status'],
                            creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
    return result.returncode == 0


def shortcut(root=ROOT):
    # PowerShell consumes paths through the environment, never interpolated source code.
    env = os.environ.copy()
    env['LUJOSHOP_ROOT'] = str(root)
    run(['powershell.exe', '-NoProfile', '-Command',
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; $desktop=[Environment]::GetFolderPath('Desktop'); if(-not $desktop){throw 'Windows no permite acceder al escritorio del usuario actual.'}; $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut((Join-Path $desktop ('LujoShop-'+(Split-Path $env:LUJOSHOP_ROOT -Leaf)+'.lnk'))); $s.TargetPath=Join-Path $env:LUJOSHOP_ROOT 'LujoShop.vbs'; $s.WorkingDirectory=$env:LUJOSHOP_ROOT; $s.IconLocation=(Join-Path $env:LUJOSHOP_ROOT 'static\\img\\lujoshop.ico'); $s.Save()"], env=env)

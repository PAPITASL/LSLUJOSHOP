# LujoShop en este computador

Abre **LujoShop.vbs** con doble clic. Puedes crear un acceso directo a ese archivo desde el Explorador de Windows. La aplicación se abre en su propia ventana y termina su servidor local al cerrarla.

Utiliza la base PostgreSQL y las credenciales del `.env` existente. Inicia sesión con el mismo usuario de la web. PostgreSQL debe estar funcionando; no necesitas conexión a internet para el uso diario. El servidor escucha exclusivamente en este computador.

Los informes PDF y Excel se descargan desde la ventana de la aplicación. La ventana utiliza Microsoft Edge WebView2 Runtime, que debe estar instalado en Windows.

## Dependencias

Desde esta carpeta, si hace falta reinstalarlas:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
```

Para diagnosticar el inicio con consola:

```powershell
.\venv\Scripts\python.exe desktop.py
```

Los errores de inicio se registran en `%TEMP%\LujoShop-error.log`. El arranque no modifica el esquema ni crea una base nueva. No elimines la carpeta del proyecto ni PostgreSQL: contienen la aplicación y sus datos. Las copias de seguridad de PostgreSQL deben hacerse con `pg_dump`; copiar el archivo vacío `db.sqlite3` no respalda esta aplicación.

# LujoShop para Windows: apertura y recuperación

Abra **LujoShop.vbs** con doble clic. **Crear acceso directo.cmd** crea el acceso con el logo. Conserve toda la carpeta. Requisitos: Windows 10 22H2 o Windows 11 de 64 bits, .NET Framework 4.8 (componente de Windows), Microsoft Edge WebView2 y Visual C++ v14 x64. Se incluyen los instaladores completos oficiales de WebView2 y Visual C++ en offline-installers: abra **Instalar requisitos.cmd** si hacen falta. Pueden solicitar permisos de administrador y un reinicio; no se ejecutan automáticamente ni se reemplazan componentes compartidos durante la restauración. Windows y .NET Framework deben estar instalados por separado. No se garantiza funcionamiento en otro equipo hasta comprobar estos requisitos.

## Datos y procesos

Se conservan Django, PostgreSQL 18, pantallas y cuentas. El SQLite vacío no se usa. La instalación original se conecta al servicio PostgreSQL existente en localhost:5432 mediante `.env`; Windows administra ese servicio compartido (postgresql-x64-18), actualmente iniciado y configurado para inicio automático. LujoShop nunca lo detiene ni cambia su configuración, porque podría servir a otras aplicaciones. Debe estar iniciado para usar la instalación original.

Cada recuperación crea un clúster PostgreSQL independiente en `local-data/postgres`, con nuevas credenciales técnicas en `installation.json`. Conserva las contraseñas de los usuarios de LujoShop. Su base se inicia y detiene con la ventana y con el respaldo, sin servicio Windows ni permisos de administrador. PostgreSQL y Waitress escuchan solo en 127.0.0.1 con puertos libres. No ejecute dos copias sobre la misma carpeta. No desconecte el disco ni apague Windows mientras trabaja. Tras un cierre forzado, si aparece «base privada ya en uso», no borre archivos PID: cierre los procesos de esa instalación o reinicie Windows.

## Crear y guardar un respaldo

El PostgreSQL compartido original conserva `listen_addresses=*`. LujoShop lo usa por loopback, pero ese servicio existente no se reconfiguró ni reinició para no afectar otras aplicaciones. Su exposición en la red depende además de sus reglas de acceso y del firewall, que no se modificaron ni se probaron desde otro equipo. La limitación estricta a 127.0.0.1 se aplica al servidor de la ventana y a los PostgreSQL privados de las recuperaciones. Si se continúa usando el servicio compartido, su configuración de red debe revisarla quien lo administra.

1. Cierre LujoShop. Cierre también servidores de desarrollo o accesos web que usen esta instalación. El bloqueo comprueba las ventanas abiertas con el lanzador; no puede impedir escritores externos al servicio compartido.
2. Abra **Crear respaldo.cmd**. Espere el aviso de éxito; la ventana muestra errores y permanece abierta.
3. Guarde el ZIP fechado y su archivo `.zip.sha256` de `backups` en un disco externo o USB con suficiente espacio. No copie un archivo `.partial`. Es recomendable un disco con BitLocker y una segunda copia en otro lugar. Expulse la unidad después de copiar.

El respaldo usa `pg_dump` en formato personalizado y una instantánea coherente de PostgreSQL, con auditoría de todas las filas. Incluye el código, recursos, fotografías existentes, archivos del proyecto, artefactos, Python con paquetes, binarios/bibliotecas de PostgreSQL y licencias disponibles. No copia los archivos físicos de una base en ejecución ni depende del entorno virtual original. Actualmente los modelos no tienen campos de cargas persistentes; Excel se procesa desde la solicitud. Descargas guardadas fuera de la carpeta del proyecto no se incluyen: respáldelas por separado. No agregue carpetas con adjuntos externos sin adaptar este procedimiento.

El ZIP contiene información sensible: clientes, teléfonos, correos, ventas, costos, usuarios, hashes de las contraseñas y la clave de Django. No está cifrado y permite recuperar las cuentas; entréguelo solo a personas autorizadas. La contraseña técnica del PostgreSQL original se excluye. SHA256 detecta daños accidentales; no demuestra autenticidad ante un atacante que reemplace también el manifiesto.

## Recuperar sin internet

1. Copie ZIP y SHA256 a un disco local del destino. Opcionalmente compruebe el hash con `Get-FileHash` y compárelo con el archivo `.sha256`.
2. Extraiga **todo** el ZIP a una carpeta vacía. Nunca abra el instalador desde dentro del ZIP.
3. Si faltan los componentes de Microsoft, abra primero **Instalar requisitos.cmd**. Luego abra **Instalar y restaurar.cmd** en la raíz extraída. Elija una carpeta padre local con espacio suficiente. Se crea una subcarpeta nueva; nunca se sobrescribe una existente.
4. Espere la comprobación SHA256 de cada archivo, la restauración transaccional y la comparación de todas las tablas. Solo se crea el acceso directo después de superar esas verificaciones. Si falla, conserve el registro y use otro destino para reintentar.
5. Abra el acceso directo e ingrese con su usuario y contraseña habituales. Puede crear nuevos respaldos desde la carpeta recuperada.

Los archivos `installation.json`, `.env`, `runtime` y `local-data` de una instalación recuperada son necesarios: no los borre ni comparta. La carpeta extraída de respaldo permanece inalterada para poder volver a usarla. Una restauración fallida queda marcada `RESTAURACION-FALLIDA.txt`; no es una instalación utilizable.

## Funciones sin conexión y diagnóstico

Bootstrap, iconos, fuentes, scripts y logos son locales. Inventario, clientes, órdenes, pagos, informes PDF e importación/plantillas Excel trabajan localmente. La consulta de TRM oficial necesita internet; puede introducir la tasa manualmente y continuar. No se inventa una tasa vigente sin conexión. Para imprimir, descargue el PDF y ábralo en su visor de PDF de Windows.

Errores de apertura: `%TEMP%/LujoShop-error.log`; respaldo/recuperación: `%TEMP%/LujoShop-recuperacion-error.log`; base privada: `local-data/postgres.log`. No se ejecutan migraciones automáticamente. Los cambios futuros del esquema requieren una revisión y un respaldo previo.

Consulte `VERIFICACION.md` para los resultados y las limitaciones de las pruebas realizadas en este computador.

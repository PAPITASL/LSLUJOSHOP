# Verificación en este computador — 12 y 13 de noviembre de 2026

Se trabajó en Windows, en el equipo original. **No se probó otro computador.** La instalación original y su servicio PostgreSQL compartido se conservaron. Había también un servidor de desarrollo independiente; no se detuvo ni se incorporó al ciclo privado de la aplicación.

## Comprobaciones realizadas

- Las 91 pruebas existentes de gestión pasaron, con `config.test_settings` y una base SQLite de pruebas aislada. `pip check` no encontró dependencias rotas. Esto complementa las pruebas reales de PostgreSQL; no las sustituye.
- Se creó un respaldo PostgreSQL real con `pg_dump` personalizado. El inventario y el volcado comparten la misma instantánea repetible. La primera instantánea contenía 19 tablas: 1 usuario, 281 clientes, 368 productos, 152 órdenes, 258 detalles, 76 abonos, 152 comisiones, 440 movimientos y 3 vendedores; recibos sin filas.
- Se comprobaron los SHA256 de los archivos y la integridad CRC del ZIP. Una prueba controlada alteró un archivo y comprobó que el verificador lo rechaza.
- Se ejecutó la restauración completa en `restoration-tests/Recovered-final`, en una carpeta nueva y un clúster PostgreSQL nuevo, mediante las herramientas incluidas. Se compararon cantidades y hashes de todas las filas de todas las tablas, incluidas cuentas, contraseñas con hash, permisos y sesiones. Coincidieron. El acceso directo de la recuperación se creó con el icono del proyecto.
- Con el Python portátil de esa instalación se comprobó la autenticación real: rechazo de una contraseña incorrecta y aceptación de la correcta de una cuenta temporal. Se verificaron dashboard, reportes, finanzas, pagadas, costos/entregas pendientes, BOG y las nueve listas comerciales. Se siguieron las redirecciones normales de selección de mes.
- Se generaron y leyeron PDF de clientes, órdenes y recibo de una orden existente; se descargaron las tres plantillas Excel y se cargó un Excel real de cliente mediante el formulario HTTP. Las escrituras de prueba se revirtieron en una transacción; el inventario de todas las tablas siguió coincidiendo después de la prueba.
- Se simuló un fallo de red de la TRM y se comprobó la respuesta que ofrece introducir la tasa manualmente. Se revisaron los recursos de las plantillas: estilos, iconos, fuentes y scripts son locales.
- La ventana WebView2 cargó en la instalación original y en la recuperada, con cierre automático de prueba. Se comprobó que el puerto HTTP dejó de aceptar conexiones y que el PostgreSQL privado quedó detenido. Los registros muestran escucha exclusiva en 127.0.0.1 y cierre de la base. También se comprobó el cierre de PostgreSQL cuando una prueba falló.
- Se verificó el selector de carpetas Tcl/Tk con el Python portátil. Los instaladores completos de WebView2 y Visual C++ incluidos tienen firma Authenticode válida de Microsoft Corporation; no se instalaron porque el equipo ya tiene los componentes.
- El bloqueo entre respaldo y apertura rechazó el arranque durante un respaldo con un mensaje comprensible y registro de error. Se corrigió el manejo de salida de `pg_ctl` para que no espere indebidamente al proceso servidor en Windows.

Las pruebas de ventana, Tcl/Tk e inicialización PostgreSQL necesitaron ejecutarse fuera del aislamiento de las herramientas: ese aislamiento impidió la carga gráfica y la creación del token restringido que PostgreSQL usa. Esto no requirió cambiar los datos ni la configuración del servicio original. Las carpetas de pruebas fallidas se conservaron identificadas; no son instalaciones para usar.

## Alcance y pendientes

El PostgreSQL compartido original tiene `listen_addresses=*`, aunque la conexión de LujoShop es por loopback. No se cambiaron sus interfaces, reglas de acceso ni firewall para evitar afectar otros consumidores. Los servidores creados por esta adaptación sí se limitan a 127.0.0.1; queda pendiente revisar la configuración del servicio compartido si se sigue utilizando la instalación original.

La contraseña personal del usuario original no se solicitó, adivinó ni cambió. Se comprobó la conservación íntegra de sus hashes y se probó el mecanismo de autenticación con una cuenta temporal; falta que el propietario confirme su entrada habitual en el computador destino.

No se desconectó físicamente la red del equipo ni se imprimió en una impresora real. La comprobación de desconexión consistió en revisar recursos locales y simular el fallo de TRM. La generación/lectura de PDF, la carga Excel y la ventana se probaron; el diálogo de guardado de descargas, el visor PDF, la impresión física, las políticas antivirus y los instaladores de requisitos deben comprobarse en el computador destino.

La copia final se genera nuevamente desde el PostgreSQL original para recoger el estado más reciente de las cuentas y sesiones. El archivo `database-audit.json` dentro de cada ZIP es la referencia exacta de sus datos; no contiene valores de clientes ni contraseñas, solo cantidades y hashes. Conserve el ZIP y su `.zip.sha256` juntos. Los resultados funcionales detallados de la copia de prueba están en `restoration-tests/Recovered-final/SMOKE-RESULTS.json`.

Se creó además un respaldo real desde la instalación recuperada con su Python y PostgreSQL portátiles. El ZIP y su SHA256 se generaron correctamente, y se comprobó que su PostgreSQL quedó detenido después del respaldo.

La entrega final LujoShop-respaldo-2026-11-13_08-54-20-VERIFICADO.zip se restauro tambien en una base adicional nueva de la carpeta de prueba. Se verificaron todas las tablas y la configuracion regional original Spanish_Colombia.1252; las pruebas funcionales se repitieron sobre esa base y pasaron. El ZIP final incluye una proteccion que rechaza instalar dentro de la carpeta extraida del propio respaldo; se probo ese rechazo antes de copiar archivos o crear bases.

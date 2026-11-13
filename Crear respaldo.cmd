@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" set "PY=%~dp0venv\Scripts\python.exe"
echo Cierre LujoShop y otras ventanas web de esta instalacion.
echo Se comprobara que la aplicacion de escritorio este cerrada.
echo Espere hasta ver el resultado. No cierre esta ventana.
"%PY%" "%~dp0recovery.py" backup
if errorlevel 1 echo NO se completo el respaldo. Revise el error anterior.
pause

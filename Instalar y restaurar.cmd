@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0app\runtime\python\python.exe" (
 echo Extraiga COMPLETAMENTE el ZIP de respaldo y abra este archivo desde la carpeta extraida.
 pause
 exit /b 1
)
echo Se comprobara cada archivo y se creara una instalacion nueva.
echo No cierre esta ventana hasta que termine.
set "PYTHONDONTWRITEBYTECODE=1"
"%~dp0app\runtime\python\python.exe" -B "%~dp0app\recovery.py" restore --source "%~dp0."
if errorlevel 1 echo NO se completo la restauracion. Revise el error anterior.
pause

@echo off
chcp 65001 >nul
set "TOOLS=%~dp0offline-installers"
if exist "%~dp0app\offline-installers" set "TOOLS=%~dp0app\offline-installers"
echo Instaladores oficiales de Microsoft para uso SIN internet.
echo Pueden solicitar permisos de administrador y mostrar su licencia.
echo Si ya estan instalados, puede cerrar este archivo.
pause
if not exist "%TOOLS%\VC_redist.x64.exe" goto missing
if not exist "%TOOLS%\MicrosoftEdgeWebView2RuntimeInstallerX64.exe" goto missing
start "" /wait "%TOOLS%\VC_redist.x64.exe" /install /passive /norestart
set "RC=%errorlevel%"
if "%RC%"=="3010" echo Windows solicita reiniciar para completar Visual C++.
if "%RC%"=="0" goto webview
if "%RC%"=="1638" goto webview
if "%RC%"=="3010" goto webview
goto failed
:webview
start "" /wait "%TOOLS%\MicrosoftEdgeWebView2RuntimeInstallerX64.exe" /install
if errorlevel 1 goto failed
echo Requisitos instalados. Si Windows lo solicita, reinicie antes de restaurar.
pause
exit /b 0
:missing
echo Faltan instaladores. Use el respaldo completo con la carpeta offline-installers.
pause
exit /b 1
:failed
echo Revise el aviso del instalador. Si ya existe una version mas reciente, conserve esa version.
pause
exit /b 1

# Componentes de Microsoft incluidos

Descargados el 12 de noviembre de 2026. Ambos ejecutables tienen firma Authenticode válida de Microsoft Corporation en este computador. No se ejecutaron los instaladores: este equipo ya tiene los componentes necesarios. Su instalación en un equipo destino puede solicitar permisos administrativos y reiniciar Windows.

- `MicrosoftEdgeWebView2RuntimeInstallerX64.exe`: instalador completo Evergreen x64, 214990032 bytes. Descarga oficial: https://go.microsoft.com/fwlink/?linkid=2124701 . Información y condiciones de Microsoft: https://developer.microsoft.com/en-us/microsoft-edge/webview2/ y https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution .
- `VC_redist.x64.exe`: redistribuible Visual C++ v14 x64, 18863624 bytes. Descarga oficial: https://aka.ms/vc14/vc_redist.x64.exe . Información y condiciones: https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist .

Se distribuyen los instaladores íntegros para los requisitos de esta aplicación; sus licencias pertenecen a Microsoft. No son el pequeño bootstrapper que descarga componentes de internet. Los hashes de los archivos se incluyen en el manifiesto del respaldo. Windows y su componente .NET Framework 4.8 siguen siendo requisitos del equipo; no se incluye una licencia ni un instalador de Windows.

Option Explicit
Dim shell, files, root, python, quote, log, problem
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = root & "\venv\Scripts\pythonw.exe"
If files.FileExists(root & "\runtime\python\pythonw.exe") Then
    python = root & "\runtime\python\pythonw.exe"
End If
quote = Chr(34)
If Not files.FileExists(python) Then
    Set log = files.OpenTextFile(shell.ExpandEnvironmentStrings("%TEMP%") & "\LujoShop-error.log", 8, True)
    log.WriteLine Now & " - No se encuentra Python de LujoShop: " & python
    log.Close
    MsgBox "No se encuentra Python de LujoShop en: " & python, vbCritical, "LujoShop"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
On Error Resume Next
shell.Run quote & python & quote & " " & quote & root & "\desktop.py" & quote, 0, False
If Err.Number <> 0 Then
    problem = Err.Description
    Err.Clear
    Set log = files.OpenTextFile(shell.ExpandEnvironmentStrings("%TEMP%") & "\LujoShop-error.log", 8, True)
    log.WriteLine Now & " - No fue posible ejecutar LujoShop: " & problem
    log.Close
    MsgBox "No fue posible abrir LujoShop: " & problem & vbCrLf & "Consulte %TEMP%\LujoShop-error.log", vbCritical, "LujoShop"
    WScript.Quit 1
End If

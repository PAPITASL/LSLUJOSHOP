Option Explicit
Dim shell, files, root, python, quote
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = root & "\venv\Scripts\pythonw.exe"
quote = Chr(34)
If Not files.FileExists(python) Then
    MsgBox "No se encuentra Python de LujoShop en: " & python, vbCritical, "LujoShop"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run quote & python & quote & " " & quote & root & "\desktop.py" & quote, 0, False

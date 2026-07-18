Dim fso, dir, shell
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("Shell.Application")

dir = fso.GetParentFolderName(WScript.ScriptFullName)

shell.ShellExecute "powershell.exe", _
  "-NoProfile -ExecutionPolicy Bypass -File """ & dir & "\server.ps1""", _
  dir, "runas", 1

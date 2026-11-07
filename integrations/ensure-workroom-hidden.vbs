Option Explicit
Dim shell, fso, launcher, powershell, command, result
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
launcher = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "restart-workroom-preview.ps1")
powershell = shell.ExpandEnvironmentStrings("%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe")
command = Chr(34) & powershell & Chr(34) & " -NoProfile -NonInteractive -WindowStyle Hidden -File " & Chr(34) & launcher & Chr(34) & " -Action Ensure"
' wscript is GUI-subsystem; style 0 hides the console before PowerShell starts.
result = shell.Run(command, 0, True)
WScript.Quit result

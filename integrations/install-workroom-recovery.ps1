# Named current-user recovery; no password, elevation, network change or other app management.
$ErrorActionPreference='Stop'
$taskName='ONOes Mesh Workroom Recovery'
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$launcher=Join-Path $PSScriptRoot 'restart-workroom-preview.ps1'
$legacyExe=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$legacyArguments='-NoProfile -WindowStyle Hidden -File "'+$launcher+'" -Action Ensure'
$exe=Join-Path $env:WINDIR 'System32\wscript.exe'
$arguments='//B //Nologo "'+(Join-Path $PSScriptRoot 'ensure-workroom-hidden.vbs')+'"'
$current=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if($current){
  $ours=$current.Actions.Count -eq 1 -and (($current.Actions[0].Arguments -eq $arguments -and $current.Actions[0].Execute -eq $exe) -or ($current.Actions[0].Arguments -eq $legacyArguments -and $current.Actions[0].Execute -eq $legacyExe))
  if(!$ours){throw 'Existing named task has different ownership; refusing replacement.'}
}
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory $root
$logon=New-ScheduledTaskTrigger -AtLogOn -User $user
$repeat=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if($current){
  # Change only how it launches. Preserve the existing principal/triggers/settings.
  Set-ScheduledTask -TaskName $taskName -Action $action | Select-Object TaskName,State
}else{
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon,$repeat) -Principal $principal -Settings $settings -Description 'Recover only the named owned Mesh Workroom preview if absent; intentional named Stop pauses recovery. No task/agent replay.' -Force | Select-Object TaskName,State
}
Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $root 'data/workroom-preview/recovery-task.xml')

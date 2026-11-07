param([ValidateSet('Status','Start')][string]$Action='Status')
$ErrorActionPreference='Stop'
$relayRoot='D:\Dev\Onoes-Relay'
$relayScript=Join-Path $relayRoot 'relay_server.py'
$workspace=Split-Path $PSScriptRoot
$parentFolder=Split-Path $workspace
$python=Join-Path $relayRoot '.venv\Scripts\pythonw.exe'
$allowedPython=@($python,'C:\Python314\pythonw.exe')
$relayCommandPattern='^"?('+(($allowedPython | ForEach-Object {[regex]::Escape($_)}) -join '|')+')"?\s+"?'+[regex]::Escape($relayScript)+'"?\s*$'
$mutex=New-Object Threading.Mutex($false,'Local\ONOesMeshRelayStart')
$held=$false
function Read-RelayStatus {
  $listeners=@(Get-NetTCPConnection -State Listen -LocalPort 8787 -ErrorAction SilentlyContinue)
  $processes=@(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine -match $relayCommandPattern -and $allowedPython -contains $_.ExecutablePath
  })
  $listener=$null;$healthy=$false;$unowned=$false
  if($listeners.Count -gt 0){
    $owners=@($listeners.OwningProcess | Select-Object -Unique)
    if($owners.Count -ne 1 -or @($listeners | Where-Object {$_.LocalAddress -ne '127.0.0.1'}).Count -gt 0){$unowned=$true}
    else {
      $listener=$processes | Where-Object {$_.ProcessId -eq $owners[0]} | Select-Object -First 1
      if(!$listener){$unowned=$true}
      else {try{$healthy=(Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/' -MaximumRedirection 0 -TimeoutSec 2).StatusCode -eq 200}catch{}}
    }
  }
  [pscustomobject]@{Schema='onoes-relay-service/v1';AppName="ONOe's Relay";Running=[bool]$listener;Healthy=$healthy;UnownedPort=$unowned;Starting=(!$listener -and $processes.Count -gt 0);ProcessIds=@($processes.ProcessId);ListenerId=$(if($listener){$listener.ProcessId}else{$null});Port=8787}
}
try {
  $held=$mutex.WaitOne(5000)
  if(!$held){throw 'Another Relay start check is in progress. No second start performed.'}
  $status=Read-RelayStatus
  if($Action -eq 'Status'){$status | ConvertTo-Json;return}
  if($status.UnownedPort){throw 'Relay port has an unrecognized owner or address. Nothing stopped or started.'}
  if($status.Running -or $status.Starting){$status | ConvertTo-Json;return}
  foreach($file in @($python,$relayScript,(Join-Path $relayRoot 'config.json'),(Join-Path $relayRoot '.private\relay.key'))){if(!(Test-Path -LiteralPath $file -PathType Leaf)){throw 'Existing Relay installation is incomplete. Nothing started.'}}
  $config=Get-Content -LiteralPath (Join-Path $relayRoot 'config.json') -Raw | ConvertFrom-Json
  if($null -ne $config.port -and $config.port -ne 8787){throw 'Configured Relay port changed. Inspect before starting.'}
  $started=Start-Process -FilePath $python -ArgumentList ('"'+$relayScript+'"') -WorkingDirectory $relayRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $parentFolder 'workroom-relay-recovery.out.log') -RedirectStandardError (Join-Path $parentFolder 'workroom-relay-recovery.err.log') -PassThru
  $native=Get-CimInstance Win32_Process -Filter "ProcessId=$($started.Id)"
  if(!$native){throw 'Started Relay launcher exited. Inspect the retained log; no automatic retry.'}
  @{Schema='onoes-owned-process/v1';AppName="ONOe's Relay";Id=$started.Id;Path=$native.ExecutablePath;StartTime=$started.StartTime.ToString('o');WorkingDirectory=$relayRoot;CommandLine=$native.CommandLine;Port=8787} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $parentFolder 'workroom-relay-process.json')
  for($attempt=0;$attempt -lt 20;$attempt++){
    $status=Read-RelayStatus
    if($status.Running -or $status.UnownedPort){break}
    Start-Sleep -Milliseconds 200
  }
  $status | ConvertTo-Json
} finally {if($held){$mutex.ReleaseMutex()};$mutex.Dispose()}

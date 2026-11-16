param(
  [ValidateSet('Status','Start','Restart','Stop','Ensure')][string]$Action = 'Restart',
  [string]$NativeMindProfile, [string]$NativeMindSha256, [string]$NativeMindApproval
)
$ErrorActionPreference = 'Stop'
$appName = "ONOe's Mesh - Workroom"
$workroomRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$workroomParent = Split-Path $workroomRoot
$receiptPath = Join-Path $workroomParent 'workroom-ab-preview-process.json'
$databasePath = Join-Path $workroomRoot 'data/workroom-preview/tasks.sqlite'
if ($Action -ne 'Status' -and $Action -ne 'Stop' -and !(Test-Path -LiteralPath $databasePath)) { throw 'Expected Workroom database absent; refusing accidental empty deployment.' }
$pausePath = Join-Path $workroomRoot 'data/workroom-preview/recovery-paused'
$mutexName = 'Local\ONOesMeshWorkroom-' + ([System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($workroomRoot))).Replace('-','').Substring(0,16))
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
$mutexHeld = $false
try {
  try { $mutexHeld = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $mutexHeld = $true }
  if (!$mutexHeld) { throw 'Another named Mesh launcher operation is in progress; nothing changed.' }
$owned = $null
if (Test-Path -LiteralPath $receiptPath) {
  $receipt = Get-Content -LiteralPath $receiptPath | ConvertFrom-Json
  $owned = Get-Process -Id $receipt.Id -ErrorAction SilentlyContinue
  if ($owned) {
    if ($owned.Path -ne $receipt.Path -or $owned.StartTime.ToUniversalTime() -ne ([datetime]$receipt.StartTime).ToUniversalTime()) { throw 'Preview process identity mismatch; nothing stopped.' }
    $native = Get-CimInstance Win32_Process -Filter "ProcessId = $($owned.Id)"
    if (!$native -or ($receipt.CommandLine -and $native.CommandLine -cne $receipt.CommandLine)) { throw 'Preview command identity mismatch; nothing stopped.' }
    if ($receipt.AppName -and ($receipt.AppName -ne $appName -or $receipt.WorkingDirectory -ne $workroomRoot)) { throw 'Preview app ownership mismatch; nothing stopped.' }
    # Legacy receipts still require the original exact executable/start time plus known entry point.
    if (!$receipt.CommandLine -and $native.CommandLine -notmatch '^"C:\\Program Files\\node.exe"\s+serve\.mjs\s*$') { throw 'Unrecognized legacy preview command; nothing stopped.' }
  }
}
if ($Action -eq 'Status') {
  $listener = Get-NetTCPConnection -State Listen -LocalPort 4320 -ErrorAction SilentlyContinue
  $healthy = $false
  if ($owned -and $listener -and @($listener.OwningProcess) -contains $owned.Id) {
    try { $healthy = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4320/' -TimeoutSec 3).StatusCode -eq 200 } catch { }
  }
  [pscustomobject]@{ AppName=$appName; Running=[bool]$owned; Healthy=$healthy; Pid=$(if($owned){$owned.Id}else{$null}); Url='https://emitchell.tail8c4a75.ts.net:8453/#workroom'; Receipt=$receiptPath } | ConvertTo-Json
  return
}
if ($Action -eq 'Ensure') {
  if (Test-Path -LiteralPath $pausePath) { Write-Output 'Mesh recovery is intentionally paused.'; return }
  if ($owned) { Write-Output "$appName is running; no restart performed."; return }
}
if ($Action -eq 'Start' -and $owned) { throw 'Mesh is already running. Use Status to inspect it or Restart deliberately.' }
$settings = @{
  MESH_PREVIEW_PORT='4320'; MESH_DATA_DIR='data/workroom-preview'; MESH_RELAY='1'; MESH_RELAY_MODE='http'; MESH_NIMS='1'; MESH_MODEL_OBSERVATION='1'; MESH_SIMPLE_FLOW='0'; MESH_NEMOTRON_CONTROL='1';
  MESH_TAILSCALE_LOGIN='emitchell109@gmail.com'; MESH_TAILSCALE_HOST='emitchell.tail8c4a75.ts.net:8453'
  MESH_GATE_KEY_FILE='D:/Dev/Onoes-Relay/.private/relay.key'
}
$nativeMindRequested = [bool]($NativeMindProfile -or $NativeMindSha256 -or $NativeMindApproval)
if ($nativeMindRequested) {
  if ($Action -notin @('Start','Restart') -or !$NativeMindProfile -or !$NativeMindApproval -or $NativeMindSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'An explicit native Mind Start/Restart and all approved inputs are required.' }
  if ((Get-FileHash -LiteralPath $NativeMindProfile -Algorithm SHA256).Hash.ToLowerInvariant() -cne $NativeMindSha256) { throw 'Native Mind launch profile changed; nothing stopped.' }
  $mindLaunch = Get-Content -LiteralPath $NativeMindProfile -Raw | ConvertFrom-Json
  $mindHelper = Join-Path $PSScriptRoot 'mind-recovery-candidate/mesh_launch_candidate.py'
  $mindPython = 'C:\Python314\python.exe'
  if ($mindLaunch.pythonExecutable -ine $mindPython -or $mindLaunch.nodeExecutable -ine 'C:\Program Files\node.exe' -or
      (Get-FileHash -LiteralPath $mindPython -Algorithm SHA256).Hash.ToLowerInvariant() -cne $mindLaunch.pythonSha256 -or
      (Get-FileHash -LiteralPath $mindHelper -Algorithm SHA256).Hash.ToLowerInvariant() -cne $mindLaunch.sourceHashes.PSObject.Properties[$mindHelper].Value) { throw 'Native Mind launcher runtime changed; nothing stopped.' }
  $mindPreviewText = & $mindPython $mindHelper --profile $NativeMindProfile --sha256 $NativeMindSha256 --approval $NativeMindApproval
  if ($LASTEXITCODE -ne 0) { throw 'Native Mind reader/profile check refused; nothing stopped.' }
  $mindPreview = $mindPreviewText | ConvertFrom-Json
  if (!$mindPreview.ready -or !$mindPreview.createsNothing -or @($mindPreview.settings.PSObject.Properties).Count -ne $settings.Count) { throw 'Native Mind preview refused; nothing stopped.' }
  foreach ($key in $settings.Keys) { if ($mindPreview.settings.$key -cne $settings[$key]) { throw 'Native Mind settings differ from the named Mesh launcher; nothing stopped.' } }
}
if ($owned) {
  Write-Output "Stopping verified $appName (PID $($owned.Id))."
  Stop-Process -InputObject $owned
  if (!$owned.WaitForExit(5000)) { throw 'Owned preview did not stop.' }
}
if ($Action -eq 'Stop') { Set-Content -LiteralPath $pausePath -Value 'Intentional named Stop; Start or Restart resumes recovery.'; Write-Output "$appName stopped; automatic recovery paused; other apps untouched."; return }
if (Get-NetTCPConnection -State Listen -LocalPort 4320 -ErrorAction SilentlyContinue) { throw 'Port 4320 is occupied; refusing to stop an unowned listener.' }
$previous = @{}
try {
  foreach ($key in $settings.Keys) { $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process'); [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process') }
  $entryPoint = Join-Path $workroomRoot 'serve.mjs'
  if ($nativeMindRequested) {
    $mindChildText = & $mindPython $mindHelper --profile $NativeMindProfile --sha256 $NativeMindSha256 --approval $NativeMindApproval --launch
    if ($LASTEXITCODE -ne 0) { throw 'Native Mind launch uncertain/refused. Preserve its private attempt; do not retry.' }
    $mindChild = $mindChildText | ConvertFrom-Json
    $started = Get-Process -Id $mindChild.pid -ErrorAction Stop
    if ($started.Path -ine $mindLaunch.nodeExecutable -or $started.StartTime.ToUniversalTime().ToFileTimeUtc() -ne $mindChild.creationTicks) { throw 'Native Mind process identity is uncertain; preserve its private attempt and do not retry.' }
  } else {
    $started = Start-Process -FilePath 'C:\Program Files\node.exe' -ArgumentList ('"' + $entryPoint + '"') -WorkingDirectory $workroomRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $workroomParent 'workroom-ab-preview.out.log') -RedirectStandardError (Join-Path $workroomParent 'workroom-ab-preview.err.log') -PassThru
  }
  $started.Refresh()
  $native = Get-CimInstance Win32_Process -Filter "ProcessId = $($started.Id)"
  if (!$native) { throw 'Started process exited before ownership could be recorded.' }
  @{Schema='onoes-owned-process/v1';AppName=$appName;WorkingDirectory=$workroomRoot;EntryPoint=$entryPoint;Port=4320;Url='https://emitchell.tail8c4a75.ts.net:8453/#workroom';CommandLine=$native.CommandLine;Id=$started.Id;StartTime=$started.StartTime.ToString('o');Path=$started.Path} | ConvertTo-Json | Set-Content -LiteralPath $receiptPath
} finally {
  foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
}
$healthy = $false
for ($attempt=0; $attempt -lt 15; $attempt++) {
  try { $probe=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4320/' -TimeoutSec 2; if ($probe.StatusCode -eq 200) { $healthy=$true; break } } catch { }
  Start-Sleep -Milliseconds 200
}
if (!$healthy) { throw 'Preview did not become ready. Process receipt retained; inspect logs without stopping shared services.' }
if (Test-Path -LiteralPath $pausePath) { Remove-Item -LiteralPath $pausePath }
Write-Output 'Workroom preview ready. Existing private Tailscale mapping unchanged. Process receipt refreshed.'

} finally {
  if ($mutexHeld) { $mutex.ReleaseMutex() }
  $mutex.Dispose()
}

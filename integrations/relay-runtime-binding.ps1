# Launch-input custody only. No process discovery, start, stop, adoption or network calls.
function Get-RelayBindingDigest($Value) {
  $bytes=[Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 12 -Compress))
  $sha=[Security.Cryptography.SHA256]::Create()
  try {([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}
  finally {$sha.Dispose()}
}
function Get-RelayFileDigest([string]$Path) {
  $stream=[IO.File]::OpenRead($Path);$sha=[Security.Cryptography.SHA256]::Create()
  try {([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}
  finally {$sha.Dispose();$stream.Dispose()}
}
function Assert-RelayLaunchEnvironment([string]$RelayRoot) {
  foreach($item in @(@('RELAY_CONFIG_PATH','config.json'),@('RELAY_SESSION_DB','.private\relay.sqlite3'))){
    $value=[Environment]::GetEnvironmentVariable($item[0],'Process')
    if($value){
      $expected=[IO.Path]::GetFullPath((Join-Path $RelayRoot $item[1]))
      if(![IO.Path]::IsPathRooted($value) -or [IO.Path]::GetFullPath($value) -ne $expected){throw 'Relay has an unexpected config/store selector. Nothing started.'}
    }
  }
  if($env:RELAY_SKIP_OPENCLAW -eq '1'){throw 'Relay adapter-skipping is set. Inspect before starting.'}
}
function Get-RelayLaunchInputs([string]$RelayRoot,[string]$LauncherPath,[string]$HelperPath,[string]$BasePythonPath='C:\Python314\pythonw.exe') {
  $names=@('relay_server.py','relay_a2a.py','relay_a2a_reconcile.py','relay_auth.py','relay_budget.py','relay_channels.py',
    'relay_config.py','relay_db.py','relay_hermes.py','relay_inbox.py','relay_mcp.py','relay_native_receipts.py',
    'relay_notify.py','relay_openclaw.py','relay_sessions.py','relay_webpush.py','config.json','.venv\pyvenv.cfg','.venv\Scripts\pythonw.exe')
  $files=@()
  foreach($name in $names){
    $path=Join-Path $RelayRoot $name
    $file=Get-Item -LiteralPath $path -ErrorAction Stop
    if($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Relay input is not a regular file.'}
    $files+=[ordered]@{Name=$name;Sha256=(Get-RelayFileDigest $path)}
  }
  foreach($item in @(@('launcher',$LauncherPath),@('binding-helper',$HelperPath),@('base-python',$BasePythonPath))){
    $file=Get-Item -LiteralPath $item[1] -ErrorAction Stop
    if($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Relay launcher input is not a regular file.'}
    $files+=[ordered]@{Name=$item[0];Sha256=(Get-RelayFileDigest $item[1])}
  }
  $config=Get-Content -LiteralPath (Join-Path $RelayRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  $routes=@(foreach($id in @('dsh','cyony')){
    $agent=$config.agents.$id;$backend=[string]$agent.backend
    if($backend -notin @('a2a','hermes','openclaw')){$backend='unconfigured_or_unsupported'}
    [ordered]@{AgentId=$id;Backend=$backend;UrlSha256=Get-RelayBindingDigest ([string]$agent.url)}
  })
  $environment=@(Get-ChildItem Env: | Where-Object {$_.Name -like 'RELAY_*'} | Sort-Object Name | ForEach-Object {
    [ordered]@{Name=$_.Name;ValueSha256=Get-RelayBindingDigest $_.Value}
  })
  $value=[ordered]@{Schema='onoes-relay-launch-inputs/v1';Root=[IO.Path]::GetFullPath($RelayRoot);Files=$files;Routes=$routes;Environment=$environment}
  [pscustomobject]@{Digest=Get-RelayBindingDigest $value;Evidence=$value}
}
function Get-RelayProcessIdentity($Process) {
  if(!$Process){return $null}
  [pscustomobject]@{Id=[int]$Process.ProcessId;ParentId=[int]$Process.ParentProcessId;Path=[string]$Process.ExecutablePath;
    CreatedUtc=([datetime]$Process.CreationDate).ToUniversalTime().ToString('o');CommandDigest=Get-RelayBindingDigest ([string]$Process.CommandLine)}
}
function Test-RelayLaunchBinding($Receipt,$Processes,[int]$ListenerId,$Inputs) {
  $state='unverified_receipt'
  if(!$Receipt -or !$Receipt.RuntimeBinding){$state='unverified_legacy_or_missing_receipt'}
  elseif($Receipt.Schema -ne 'onoes-owned-process/v1' -or $Receipt.RuntimeBinding.Schema -ne 'onoes-relay-runtime-binding/v1'){$state='unverified_receipt_schema'}
  elseif(!$Receipt.RuntimeBinding.Inputs -or $Receipt.RuntimeBinding.Inputs.Digest -ne (Get-RelayBindingDigest $Receipt.RuntimeBinding.Inputs.Evidence)){$state='unverified_receipt_input_digest'}
  elseif(!$Receipt.RuntimeBinding.Stable){$state='unverified_unstable_launch'}
  elseif(!$Inputs -or $Receipt.RuntimeBinding.Inputs.Digest -ne $Inputs.Digest){$state='unverified_launch_inputs_changed'}
  else {
    $binding=$Receipt.RuntimeBinding
    $roots=@($Processes | Where-Object {$_.ProcessId -eq $Receipt.Id})
    $listeners=@($Processes | Where-Object {$_.ProcessId -eq $ListenerId})
    if($roots.Count -ne 1 -or $listeners.Count -ne 1){$state='unverified_process_missing'}
    else {
      $root=Get-RelayProcessIdentity $roots[0];$listener=Get-RelayProcessIdentity $listeners[0]
      if((Get-RelayBindingDigest $root) -ne (Get-RelayBindingDigest $binding.Root) -or
         (Get-RelayBindingDigest $listener) -ne (Get-RelayBindingDigest $binding.Listener) -or
         ($listener.Id -ne $root.Id -and $listener.ParentId -ne $root.Id)){$state='unverified_process_identity'}
      else {$state='matched_observed_launch_inputs'}
    }
  }
  [pscustomobject]@{State=$state;Matched=($state -eq 'matched_observed_launch_inputs');LoadedBytesAttested=$false;CanRelease=$false}
}

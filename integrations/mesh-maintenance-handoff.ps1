param([ValidateSet('Preview','Recover','Restore')][string]$Action='Preview')
$ErrorActionPreference='Stop'
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$base=Join-Path $workspace 'data\maintenance-window-preparation-20261114'
function File-Hash([string]$p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()}
function Read-Json([string]$p){Get-Content -LiteralPath $p -Raw|ConvertFrom-Json}
function Save-New([string]$p,$v){$b=[Text.Encoding]::UTF8.GetBytes(($v|ConvertTo-Json -Depth 20));$f=[IO.File]::Open($p,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$f.Write($b,0,$b.Length);$f.Flush($true)}finally{$f.Dispose()}}
function Require([bool]$ok,[string]$why){if(!$ok){throw $why}}
function Check-Pin($p){
 Require ($p.path -is [string] -and $p.sha256 -cmatch '^[a-f0-9]{64}$') 'A reviewed absolute file and hash are required.'
 Require ([IO.Path]::IsPathRooted($p.path)) 'Relative paths are not allowed.'
 $item=Get-Item -LiteralPath $p.path
 Require (!$item.PSIsContainer -and !($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'A plain pinned file is required.'
 Require ((File-Hash $p.path) -ceq $p.sha256) ('Reviewed file changed: '+$p.path)
}
function Restore-Allowed($receipt,[string]$planHash){
 if($receipt.planHash -cne $planHash){return $false}
 if($receipt.status -cin @('blocked','cancelled','blocked_after_confirmation','blocked_expired_window')){return $true}
 return ($receipt.status -ceq 'operator_returned' -and $receipt.result.planHash -ceq $planHash -and
  $receipt.result.disposition -ceq 'historical_outcome_unknown' -and $receipt.result.dispatchRemainsPaused -eq $true -and
  ![string]::IsNullOrWhiteSpace($receipt.result.recoveryId))
}
$binding=Read-Json (Join-Path $base 'restore-preparation-binding.json')
$prep=Read-Json (Join-Path $base 'postboot-preparation.json')
Require ($prep.schema -ceq 'mesh/maintenance-handoff-preparation/v1' -and $prep.windowId -ceq $binding.windowId) 'Wrong prepared handoff.'
Require ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ceq $binding.ownerSid) 'Use Eddie''s original Windows account.'
foreach($p in $prep.pins){Check-Pin $p}
$readyPath=Join-Path $base 'ready-recovery.json'
$inflight=Join-Path $base 'handoff-inflight.json'
if($Action -eq 'Preview'){
 [pscustomobject]@{status='handoff_preparation_verified';windowApproved=(Test-Path -LiteralPath (Join-Path $base 'approved-window.json'));readyRecordExists=(Test-Path -LiteralPath $readyPath);unresolvedChild=(Test-Path -LiteralPath $inflight);canRecover=$false;changesMade=$false}|ConvertTo-Json
 exit 0
}
# Neither the preparatory manifest nor a successful Preview grants live authority.
Require (Test-Path -LiteralPath $readyPath) 'Final scope, plan and exact maintenance approval are not ready. Do not restart.'
$ready=Read-Json $readyPath
Require ($ready.schema -ceq 'mesh/maintenance-handoff-ready/v1' -and $ready.windowId -ceq $binding.windowId) 'Wrong final handoff.'
foreach($p in @($ready.scope,$ready.plan,$ready.windowApproval)){Check-Pin $p}
$scope=Read-Json $ready.scope.path;$plan=Read-Json $ready.plan.path;$approved=Read-Json $ready.windowApproval.path
Require ($scope.schema -ceq 'mesh/legacy-operator-scope/v3' -and $scope.workspace -ceq $workspace) 'An approved production scope is required; drafts are refused.'
Require ($scope.additionalSources.maintenanceHandoff -ceq $PSCommandPath -and $scope.additionalSources.windowApproval -ceq $ready.windowApproval.path) 'The launcher and window authority must be frozen in the scope before plan preparation.'
Require ($plan.planHash -cmatch '^[a-f0-9]{64}$' -and $plan.targets.Count -eq 8) 'The exact eight-send plan is required.'
$boot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
Require ($approved.schema -ceq 'mesh/maintenance-preboot-approval/v1' -and $approved.owner -ceq 'Eddie' -and
 $approved.decision -ceq 'one_later_boot_recovery_and_restore' -and $approved.windowId -ceq $binding.windowId -and
 $approved.ownerSid -ceq $binding.ownerSid -and $approved.host -ceq [Environment]::MachineName -and
 $approved.preparationSha256 -ceq (File-Hash (Join-Path $base 'postboot-preparation.json')) -and
 $approved.restoreTriggerExecutionApproved -eq $true) 'The exact owner-approved interruption and startup-trigger restoration are required.'
$now=[DateTimeOffset]::UtcNow;$issued=[DateTimeOffset]::Parse($approved.authorizedAt);$expires=[DateTimeOffset]::Parse($approved.expiresAt)
Require ($issued -le $now -and $expires -gt $now -and $expires -gt $issued -and ($expires-$issued).TotalHours -le 24) 'Maintenance approval is missing or expired.'
Require ([DateTimeOffset]::Parse($boot) -gt [DateTimeOffset]::Parse($plan.preparedAt) -and [DateTimeOffset]::Parse($boot) -gt $issued) 'Use the single later boot after the frozen plan and approval.'
$mutex=[Threading.Mutex]::new($false,('Local\MeshMaintenance-'+$binding.windowId))
$held=$false
try{
 try{$held=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{throw 'A previous handoff was interrupted. Preserve receipts; do not recover or restore again.'}
 Require $held 'Another maintenance handoff is still running.'
 Require (!(Test-Path -LiteralPath $inflight)) 'A child outcome is unresolved. Preserve its receipt and do not retry or restore.'
 $windowPath=Join-Path $base 'approved-window.json'
 if(Test-Path -LiteralPath $windowPath){
  $window=Read-Json $windowPath
  Require ($window.windowId -ceq $binding.windowId -and $window.bootedAt -ceq $boot -and $window.prebootApprovalSha256 -ceq $ready.windowApproval.sha256) 'The window was already bound to a different boot or authority.'
 }else{
  $phrase='WINDOW '+$binding.windowId
  Write-Host 'Keep all other coding and agent apps closed. This records unknown historical outcomes; it does not approve old jobs or enable workers.'
  Require ((Read-Host ('Type '+$phrase+' to bind this approved window to this boot')) -ceq $phrase) 'Window confirmation cancelled.'
  Save-New $windowPath @{schema='mesh/maintenance-window-approval/v1';owner='Eddie';ownerSid=$binding.ownerSid;windowId=$binding.windowId;host=[Environment]::MachineName;bootedAt=$boot;decision='approve_reboot_recovery_restore';authorizedAt=$now.ToString('o');expiresAt=$expires.ToString('o');startupManifestSha256=$prep.startupManifestSha256;restoreHelperSha256=$prep.restoreHelperSha256;prebootApprovalSha256=$ready.windowApproval.sha256}
 }
 if($Action -eq 'Recover'){
  $attemptPath=Join-Path $workspace ('data\maintenance-console\'+$plan.planHash+'.attempt.json')
  Require (!(Test-Path -LiteralPath $attemptPath)) 'A recovery attempt already exists. Inspect the same plan; do not retry.'
  $receiptRoot=Join-Path $workspace 'data\maintenance-console'
  $before=@();if(Test-Path -LiteralPath $receiptRoot){$before=@(Get-ChildItem -LiteralPath $receiptRoot -Directory|Select-Object -ExpandProperty Name)}
  Save-New $inflight @{action='Recover';planHash=$plan.planHash;at=$now.ToString('o');status='child_outcome_unresolved'}
  Push-Location $workspace
  try{& $prep.nodePath (Join-Path $workspace 'integrations\legacy-recovery-operator.mjs') console $ready.scope.path $ready.scope.sha256 $ready.plan.path;$childExit=$LASTEXITCODE}finally{Pop-Location}
  # Exit zero is insufficient. Exactly one new durable result must identify this plan.
  $new=@(Get-ChildItem -LiteralPath $receiptRoot -Directory|Where-Object {$_.Name -notin $before})
  Require ($new.Count -eq 1) 'No unique recovery receipt. Leave the unresolved-child hold in place.'
  $receipt=Read-Json (Join-Path $new[0].FullName 'result.json')
  Require ($childExit -eq 0 -and (Restore-Allowed $receipt $plan.planHash)) 'Recovery is uncertain or failed. Leave the hold in place; do not restore startup.'
  if($receipt.status -ceq 'operator_returned'){
   & $prep.nodePath (Join-Path $workspace 'integrations\read-maintenance-recovery.mjs') $ready.scope.path $ready.plan.path
   Require ($LASTEXITCODE -eq 0) 'Recovery ledger readback failed. Leave the unresolved-child hold in place.'
  }
  $finished=Join-Path $base ('handoff-recover-'+[guid]::NewGuid()+'.json')
  Move-Item -LiteralPath $inflight -Destination $finished
  Write-Host ('Recovery receipt: '+(Join-Path $new[0].FullName 'result.json'))
  Write-Host 'Inspect the receipt. Restore is a separate explicit step; workers remain paused.'
 }else{
  $attemptPath=Join-Path $workspace ('data\maintenance-console\'+$plan.planHash+'.attempt.json')
  if(Test-Path -LiteralPath $attemptPath){
   $attempt=Read-Json $attemptPath;$receipt=Read-Json (Join-Path $attempt.receiptDirectory 'result.json')
   Require (Restore-Allowed $receipt $plan.planHash) 'Uncertain recovery: startup restoration is blocked.'
   & $prep.nodePath (Join-Path $workspace 'integrations\read-maintenance-recovery.mjs') $ready.scope.path $ready.plan.path
   Require ($LASTEXITCODE -eq 0) 'Fresh recovery ledger readback failed. Startup restoration is blocked.'
  }
  Require ((Read-Host 'Type RESTORE STARTUP to restore the original task flags and login links; enabled triggers may now run') -ceq 'RESTORE STARTUP') 'Restore cancelled.'
  Save-New $inflight @{action='Restore';planHash=$plan.planHash;at=$now.ToString('o');status='child_outcome_unresolved'}
  $restore=Join-Path $base 'prepared-startup-restore.ps1'
  $old=@(Get-ChildItem -LiteralPath $base -Directory -Filter 'Restore-attempt-*'|Select-Object -ExpandProperty Name)
  $ps=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $child=Start-Process -FilePath $ps -Verb RunAs -WindowStyle Hidden -ArgumentList @('-NoProfile','-File',('"'+$restore+'"'),'-Apply') -PassThru
  $null=$child.Handle;$child.WaitForExit();$child.Refresh()
  $new=@(Get-ChildItem -LiteralPath $base -Directory -Filter 'Restore-attempt-*'|Where-Object {$_.Name -notin $old})
  Require ($child.ExitCode -eq 0 -and $new.Count -eq 1) 'Startup restoration did not complete. Preserve the unresolved-child receipt.'
  $result=Read-Json (Join-Path $new[0].FullName 'result.json')
  Require ($result.status -ceq 'startup_restored' -and $result.guardianRemainsDisabled -eq $true -and $result.restoredEnabledTasks -eq 4 -and $result.restoredLinks -eq 3) 'Restoration result is incomplete.'
  Move-Item -LiteralPath $inflight -Destination (Join-Path $base ('handoff-restored-'+[guid]::NewGuid()+'.json'))
  Write-Host 'Original startup settings restored. This does not prove every app has started. Reopen Nims for named app and board checks; leave workers, Rook and Mind off.'
 }
}finally{if($held){$mutex.ReleaseMutex()};$mutex.Dispose()}

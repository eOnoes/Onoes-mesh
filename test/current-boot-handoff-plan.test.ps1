param(
    [Parameter(Mandatory=$true)][string]$Handoff,
    [string]$PreparedPlan,
    [string]$OwnerApproval
)
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $Handoff).Path,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'The handoff script does not parse.'}
foreach ($name in @('Read-Json','File-Hash','Require','Check-Pin','Current-Boot-Allowed','Check-StartupOnlyBoundary')) {
    $found = @($ast.FindAll({param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name
    },$true))
    if($found.Count -ne 1){throw "Expected one $name function."}
    . ([scriptblock]::Create($found[0].Extent.Text))
}

$now = [DateTimeOffset]::UtcNow
$boot = '2026-11-23T00:39:24.4505750Z'
$approval = [pscustomobject]@{
    schema='mesh/current-boot-maintenance-approval/v1'
    owner='Eddie'
    decision='one_current_boot_historical_recovery_and_restore'
    windowId='fixture'
    ownerSid='fixture-sid'
    host='fixture-host'
    bootedAt=$boot
    preparationSha256='a'*64
    restoreTriggerExecutionApproved=$true
    quietWorkspaceConfirmed=$true
    authorizedAt=$now.AddMinutes(-2).ToString('o')
    expiresAt=$now.AddMinutes(15).ToString('o')
}
$plan = [pscustomobject]@{
    schema='mesh/legacy-recovery-plan/v3'
    baselineBoot=$boot
    targets=@(1..8)
    retirementWitness=@{source='fixture'}
    preparedAt=$now.AddMinutes(-1).ToString('o')
}
function Test-Plan($candidate) {
    Current-Boot-Allowed $approval $candidate $boot 'fixture' 'fixture-sid' 'fixture-host' ($approval.preparationSha256) $now
}
if(!(Test-Plan $plan)){throw 'The canonical v3 baselineBoot plan was refused.'}
foreach ($case in @(
    @{baselineBoot='2026-11-22T00:39:24.4505750Z'},
    @{baselineBoot=$null;bootedAt=$boot},
    @{targets=@(1..7)},
    @{retirementWitness=$null},
    @{preparedAt=$now.AddMinutes(-3).ToString('o')},
    @{schema='mesh/legacy-recovery-plan/v2'}
)) {
    $candidate = $plan.PSObject.Copy()
    foreach($key in $case.Keys) {
        $candidate | Add-Member -NotePropertyName $key -NotePropertyValue $case[$key] -Force
    }
    if(Test-Plan $candidate){throw 'An invalid prepared plan passed.'}
}
if($PreparedPlan -or $OwnerApproval) {
    if(!$PreparedPlan -or !$OwnerApproval){throw 'Supply both files for the read-only captured-plan check.'}
    $actualPlan = Read-Json $PreparedPlan
    $actualApproval = Read-Json $OwnerApproval
    $prepared = [DateTimeOffset]::Parse($actualPlan.preparedAt)
    if(!(Current-Boot-Allowed $actualApproval $actualPlan $actualApproval.bootedAt $actualApproval.windowId $actualApproval.ownerSid $actualApproval.host $actualApproval.preparationSha256 $prepared)) {
        throw 'The captured controller plan was refused at the time it was prepared.'
    }
}

$workspace = Join-Path ([IO.Path]::GetTempPath()) ('mesh-handoff-check-'+[guid]::NewGuid().ToString('N'))
$window = Join-Path $workspace 'data/current-boot-window-fixture'
$receipts = Join-Path $workspace 'data/maintenance-console'
$planFile = Join-Path $window 'prepared-current-boot-plan.json'
$readyFile = Join-Path $window 'ready-recovery.json'
function Check-Cancel { Check-StartupOnlyBoundary $window $workspace $boot 'fixture' }
function Assert-Refused {
    try { Check-Cancel } catch { return }
    throw 'Unsafe startup-only cancellation was accepted.'
}
try {
    New-Item -Path $window,$receipts -ItemType Directory -Force | Out-Null
    Check-Cancel
    $plan | Add-Member -NotePropertyName workspace -NotePropertyValue $workspace
    $plan | Add-Member -NotePropertyName planHash -NotePropertyValue ('b'*64)
    $plan | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $planFile
    Check-Cancel
    $ready = @{schema='mesh/current-boot-handoff-ready/v1';windowId='fixture';
        plan=@{path=$planFile;sha256=(File-Hash $planFile)}}
    $ready | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $readyFile
    Check-Cancel
    foreach ($name in @('handoff-inflight.json','cancel-startup-inflight.json','approved-window.json','CANCEL-STARTUP-COMPLETE.json')) {
        $barrier = Join-Path $window $name
        New-Item -ItemType File -Path $barrier | Out-Null
        Assert-Refused
        Remove-Item -LiteralPath $barrier
    }
    $attempt = Join-Path $receipts ($plan.planHash+'.attempt.json')
    New-Item -ItemType File -Path $attempt | Out-Null
    Assert-Refused
    Remove-Item -LiteralPath $attempt
    $ready.plan.sha256 = '0'*64
    $ready | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $readyFile
    Assert-Refused
    Remove-Item -LiteralPath $planFile
    Assert-Refused
} finally {
    $actual = [IO.Path]::GetFullPath($workspace)
    $expectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if(([IO.Path]::GetDirectoryName($actual) -ceq $expectedParent) -and
       ([IO.Path]::GetFileName($actual) -cmatch '^mesh-handoff-check-[a-f0-9]{32}$') -and
       (Test-Path -LiteralPath $actual)) {
        Remove-Item -LiteralPath $actual -Recurse
    }
}
'Passed the v3 plan contract and startup-only cancellation checks. No recovery commands ran.'

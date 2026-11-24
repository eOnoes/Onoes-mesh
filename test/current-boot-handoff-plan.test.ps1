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
foreach ($name in @('Read-Json','Current-Boot-Allowed')) {
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
'Passed the v3 plan contract, including six rejection checks. No recovery commands ran.'

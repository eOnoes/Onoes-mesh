$ErrorActionPreference='Stop'
$source=Join-Path $PSScriptRoot '..\integrations\mesh-maintenance-handoff.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Handoff launcher has syntax errors'}
foreach($name in @('File-Hash','Require','Check-Pin','Restore-Allowed')){
 $nodes=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
 if($nodes.Count -ne 1){throw 'Missing source function'}
 . ([scriptblock]::Create($nodes[0].Extent.Text))
}
$passed=0
function Expect([bool]$condition,[string]$why){if(!$condition){throw $why};$script:passed++}
$plan='a'*64
foreach($status in @('blocked','cancelled','blocked_after_confirmation')){Expect (Restore-Allowed ([pscustomobject]@{planHash=$plan;status=$status}) $plan) $status}
$good=[pscustomobject]@{planHash=$plan;status='operator_returned';result=[pscustomobject]@{planHash=$plan;recoveryId='fixture';disposition='historical_outcome_unknown';dispatchRemainsPaused=$true}}
Expect (Restore-Allowed $good $plan) 'Exact returned result'
foreach($field in @('planHash','recoveryId','disposition','dispatchRemainsPaused')){
 $copy=$good|ConvertTo-Json -Depth 8|ConvertFrom-Json
 $copy.result.$field=$null
 Expect (!(Restore-Allowed $copy $plan)) ('Missing '+$field)
}
foreach($status in @('outcome_unknown_inspect_same_plan','failed','unknown','')){
 $copy=$good|ConvertTo-Json -Depth 8|ConvertFrom-Json;$copy.status=$status
 Expect (!(Restore-Allowed $copy $plan)) ('Refuse '+$status)
}
Expect (!(Restore-Allowed $good ('b'*64))) 'Wrong plan'
$tmp=Join-Path ([IO.Path]::GetTempPath()) ('mesh-handoff-guard-'+[guid]::NewGuid());New-Item -ItemType Directory -Path $tmp|Out-Null
try{
 $p=Join-Path $tmp 'fixture.txt';[IO.File]::WriteAllText($p,'expected')
 $pin=[pscustomobject]@{path=$p;sha256=(File-Hash $p)}
 Check-Pin $pin;$passed++
 [IO.File]::WriteAllText($p,'changed');$denied=$false;try{Check-Pin $pin}catch{$denied=$true};Expect $denied 'Changed source refused'
 Remove-Item -LiteralPath $p;$denied=$false;try{Check-Pin $pin}catch{$denied=$true};Expect $denied 'Missing source refused'
 $pin.path='relative.txt';$denied=$false;try{Check-Pin $pin}catch{$denied=$true};Expect $denied 'Relative path refused'
}finally{Remove-Item -LiteralPath $tmp}
@{status='passed';checks=$passed;actualSourceFunctions=$true;windowsStartupMutation=$false}|ConvertTo-Json

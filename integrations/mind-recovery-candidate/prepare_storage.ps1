# Prepared empty-folder action. Canonical Mind code and its existing D: folder are unchanged.
#Requires -Version 7.2
[CmdletBinding(SupportsShouldProcess=$true,ConfirmImpact='Medium')]
param(
 [Parameter(Mandatory=$true)][string]$PlanPath,
 [Parameter(Mandatory=$true)][string]$ExpectedPlanSha256,
 [switch]$Apply
)
$ErrorActionPreference='Stop'

function Require([bool]$ok,[string]$message){if(-not $ok){throw $message}}
function FullPath([string]$path){
 Require ($path -match '^[A-Za-z]:[\\/]' -and $path -notmatch '(?:^|[\\/])\.\.(?:[\\/]|$)') 'Explicit local canonical paths required.'
 $full=[IO.Path]::GetFullPath($path).TrimEnd('\')
 Require ($full.Length -gt 3) 'Drive roots cannot be targets or anchors.'
 return $full
}
function Under([string]$path,[string]$anchor){return $path.StartsWith($anchor.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)}
function Ordinary([string]$path){
 $cursor=$path
 while($cursor){
  if(Test-Path -LiteralPath $cursor){
   $item=Get-Item -LiteralPath $cursor -Force
   Require ($item.PSIsContainer -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Only ordinary directory ancestry is allowed.'
  }
  $cursor=[IO.Path]::GetDirectoryName($cursor)
 }
}
function NTFS([string]$path){
 Require ((Get-Volume -DriveLetter $path.Substring(0,1)).FileSystemType -eq 'NTFS') 'Private directories require NTFS.'
}
$operatorSid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed=@($operatorSid.Value,'S-1-5-18','S-1-5-32-544')
function Private([string]$path){
 Ordinary $path;NTFS $path
 $acl=Get-Acl -LiteralPath $path
 $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 Require ($acl.AreAccessRulesProtected -and $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -eq $operatorSid.Value -and $rules.Count -eq 3) 'Private folder ownership/rules failed.'
 $seen=@()
 foreach($rule in $rules){
  Require (-not $rule.IsInherited -and $rule.IdentityReference.Value -in $allowed -and $rule.IdentityReference.Value -notin $seen -and
   $rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
   $rule.FileSystemRights -eq [Security.AccessControl.FileSystemRights]::FullControl -and
   $rule.InheritanceFlags -eq ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit) -and
   $rule.PropagationFlags -eq [Security.AccessControl.PropagationFlags]::None) 'Private folder rule failed.'
  $seen+=$rule.IdentityReference.Value
 }
}
function Empty([string]$path){Require (@(Get-ChildItem -LiteralPath $path -Force).Count -eq 0) 'Expected empty directory is occupied.'}

$planItem=Get-Item -LiteralPath $PlanPath -Force
Require (-not $planItem.PSIsContainer -and -not ($planItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -and $planItem.Length -le 65536) 'Ordinary bounded plan file required.'
Ordinary $planItem.DirectoryName
$bytes=[IO.File]::ReadAllBytes($planItem.FullName)
$actualHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
Require ($ExpectedPlanSha256 -cmatch '^[0-9a-f]{64}$' -and $ExpectedPlanSha256 -ceq $actualHash) 'Plan fingerprint mismatch.'
$text=[Text.Encoding]::UTF8.GetString($bytes)
$document=[Text.Json.JsonDocument]::Parse($text)
try{
 Require ($document.RootElement.ValueKind -eq [Text.Json.JsonValueKind]::Object) 'Object plan required.'
 $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
 foreach($property in $document.RootElement.EnumerateObject()){
  Require ($names.Add($property.Name)) 'Duplicate plan fields refused.'
 }
 $expected=@('schema','ownerSid','existingDataDirectory','privateAnchors','encryptedAnchor','privateDirectories','encryptedDirectories')
 Require ($names.Count -eq $expected.Count -and @($names|Where-Object {$_ -cnotin $expected}).Count -eq 0) 'Unexpected plan fields.'
} finally{$document.Dispose()}
$plan=$text|ConvertFrom-Json -Depth 8
Require ($plan.schema -ceq 'onoes-mind-private-folder-plan/v1' -and $plan.ownerSid -ceq $operatorSid.Value -and $plan.ownerSid -match '^S-1-5-21-\d+-\d+-\d+-\d+$') 'Reviewed Windows owner mismatch.'
$data=FullPath $plan.existingDataDirectory
Require (Test-Path -LiteralPath $data -PathType Container) 'Approved data folder missing.'
Private $data;Empty $data
$privateAnchors=@($plan.privateAnchors|ForEach-Object {FullPath $_})
$encryptedAnchor=FullPath $plan.encryptedAnchor
Require ($privateAnchors.Count -gt 0 -and $privateAnchors.Count -le 4) 'Bounded private anchors required.'
foreach($anchor in @($privateAnchors)+@($encryptedAnchor)){
 Ordinary $anchor;Require (Test-Path -LiteralPath $anchor -PathType Container) 'Existing anchor directory required.'
}
foreach($anchor in $privateAnchors){NTFS $anchor}
$privateTargets=@($plan.privateDirectories|ForEach-Object {FullPath $_})
$encryptedTargets=@($plan.encryptedDirectories|ForEach-Object {FullPath $_})
$targets=@($privateTargets)+@($encryptedTargets)
Require ($privateTargets.Count -gt 0 -and $targets.Count -le 16) 'Bounded unique new targets required.'
$uniqueTargets=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach($target in $targets){Require ($uniqueTargets.Add($target)) 'Duplicate new targets refused.'}
$prior=@()
foreach($target in $targets){
 $isPrivate=$target -in $privateTargets
 $anchors=if($isPrivate){$privateAnchors}else{@($encryptedAnchor)}
 Require (@($anchors|Where-Object {Under $target $_}).Count -gt 0) 'Target outside reviewed anchors.'
 Require (-not (Under $target $data) -and $target -ine $data -and -not (Under $data $target)) 'Existing data directory must stay untouched.'
 Ordinary $target
 Require (-not (Test-Path -LiteralPath $target)) 'Existing targets are never altered.'
 if($isPrivate){NTFS $target}
 $parent=[IO.Path]::GetDirectoryName($target)
 Require ((Test-Path -LiteralPath $parent -PathType Container) -or $parent -in $prior) 'Every new parent must appear earlier in the exact plan.'
 $prior+=$target
}
$report=[ordered]@{schema='onoes-mind-private-folder-result/v1';planSha256=$actualHash;owner=$operatorSid.Value;
 privateDirectories=$privateTargets;encryptedDirectories=$encryptedTargets;existingDataUntouched=$true;
 keysOrDatabase=$false;servicesOrActivation=$false;applied=$false}
if(-not $Apply){$report|ConvertTo-Json -Depth 4;return}
if(-not $PSCmdlet.ShouldProcess(($targets -join ', '),'Create only these absent empty folders; private NTFS folders get operator/SYSTEM/Administrators FullControl')){
 $report|ConvertTo-Json -Depth 4;return
}
# Stable operator-controlled filesystem required; this is not hostile-race isolation.
# Failures preserve created empty folders for review, never retry or clean up.
foreach($target in $targets){
 Require ((Get-FileHash -LiteralPath $planItem.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $actualHash) 'Plan changed during action.'
 Ordinary $target
 Require (-not (Test-Path -LiteralPath $target)) 'A target appeared; nothing at that target will be changed.'
 Require (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($target)) -PathType Container) 'Reviewed parent is missing.'
 New-Item -ItemType Directory -Path $target -ErrorAction Stop|Out-Null
 Ordinary $target;Empty $target
 if($target -in $privateTargets){
  NTFS $target
  $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner($operatorSid);$acl.SetAccessRuleProtection($true,$false)
  foreach($sidText in $allowed){
   $sid=[Security.Principal.SecurityIdentifier]::new($sidText)
   $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,
    [Security.AccessControl.FileSystemRights]::FullControl,
    ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit),
    [Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))
  }
  Set-Acl -LiteralPath $target -AclObject $acl;Private $target
 }
}
foreach($target in $targets){
 Ordinary $target
 if($target -in $privateTargets){Private $target}
 foreach($child in @(Get-ChildItem -LiteralPath $target -Force)){
  Require ($child.PSIsContainer -and $child.FullName -in $targets -and -not ($child.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Unexpected content after empty-folder creation.'
 }
}
Private $data;Empty $data
$report.applied=$true
$report|ConvertTo-Json -Depth 4

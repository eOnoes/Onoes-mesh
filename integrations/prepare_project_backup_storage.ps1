# Backup work folders only. Existing initialized Mind data and anchor ACLs are never changed.
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
try {
 Require ($document.RootElement.ValueKind -eq [Text.Json.JsonValueKind]::Object) 'Object plan required.'
 $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
 foreach($property in $document.RootElement.EnumerateObject()){Require ($names.Add($property.Name)) 'Duplicate plan fields refused.'}
 $expected=@('schema','ownerSid','existingDataDirectory','privateAnchor','privateDirectories')
 Require ($names.Count -eq $expected.Count -and @($names|Where-Object {$_ -cnotin $expected}).Count -eq 0) 'Unexpected plan fields.'
 Require ($document.RootElement.GetProperty('privateDirectories').ValueKind -eq [Text.Json.JsonValueKind]::Array) 'Explicit target list required.'
} finally {$document.Dispose()}
$plan=$text|ConvertFrom-Json -Depth 8
Require ($plan.schema -ceq 'onoes-mind-backup-work-folder-plan/v1' -and $plan.ownerSid -ceq $operatorSid.Value) 'Reviewed Windows owner mismatch.'
$data=FullPath $plan.existingDataDirectory
$anchor=FullPath $plan.privateAnchor
Require ((Test-Path -LiteralPath $data -PathType Container) -and (Test-Path -LiteralPath $anchor -PathType Container)) 'Existing data and operations anchor required.'
Private $data;Private $anchor
Require ($data -ine $anchor -and -not (Under $data $anchor) -and -not (Under $anchor $data)) 'Data and operations anchor must be separate.'
$targets=@($plan.privateDirectories|ForEach-Object {FullPath $_})
Require ($targets.Count -ge 1 -and $targets.Count -le 16) 'Bounded new targets required.'
$uniqueTargets=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$prior=@()
foreach($target in $targets){
 Require ($uniqueTargets.Add($target)) 'Duplicate new target refused.'
 Require ((Under $target $anchor) -and -not (Under $target $data) -and $target -ine $data -and -not (Under $data $target)) 'Target outside operations anchor or overlaps data.'
 Ordinary $target;NTFS $target
 Require (-not (Test-Path -LiteralPath $target)) 'Existing targets are never altered.'
 $parent=[IO.Path]::GetDirectoryName($target)
 Require ((Test-Path -LiteralPath $parent -PathType Container) -or $parent -in $prior) 'Every new parent must appear earlier.'
 $prior+=$target
}
$report=[ordered]@{schema='onoes-mind-backup-work-folder-result/v1';planSha256=$actualHash;owner=$operatorSid.Value;
 privateDirectories=$targets;existingDataUntouched=$true;existingAnchorUntouched=$true;keysOrDatabase=$false;servicesOrActivation=$false;applied=$false}
if(-not $Apply){$report|ConvertTo-Json -Depth 4;return}
if(-not $PSCmdlet.ShouldProcess(($targets -join ', '),'Create only the absent backup work folders with operator/SYSTEM/Administrators access')){
 $report|ConvertTo-Json -Depth 4;return
}
# Stable operator-controlled filesystem required, not hostile-race isolation.
# Failure retains new folders for review; never delete, retry or alter an existing ACL.
foreach($target in $targets){
 Require ((Get-FileHash -LiteralPath $planItem.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $actualHash) 'Plan changed during action.'
 Private $data;Private $anchor;Ordinary $target
 Require (-not (Test-Path -LiteralPath $target)) 'Target appeared; existing folder is preserved.'
 Require (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($target)) -PathType Container) 'Reviewed parent is missing.'
 New-Item -ItemType Directory -Path $target -ErrorAction Stop|Out-Null
 Ordinary $target;Empty $target;NTFS $target
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
foreach($target in $targets){
 Ordinary $target;Private $target
 foreach($child in @(Get-ChildItem -LiteralPath $target -Force)){
  Require ($child.PSIsContainer -and $child.FullName -in $targets -and -not ($child.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Unexpected content after folder creation.'
 }
}
Private $data;Private $anchor
$report.applied=$true
$report|ConvertTo-Json -Depth 4

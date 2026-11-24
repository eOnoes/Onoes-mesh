[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Profile,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$Sha,
    [Parameter(Mandatory=$true)][string]$Approval
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$backupExit = 1
try {
    $Host.UI.RawUI.WindowTitle = 'Onoes-Mind / existing-store backup'
    if ((Get-FileHash -LiteralPath $Profile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha) {
        throw 'The approved backup profile changed.'
    }
    $settings = Get-Content -LiteralPath $Profile -Raw | ConvertFrom-Json
    $python = [string]$settings.runtime.python
    $entry = Join-Path $PSScriptRoot 'project_backup_entry.py'
    foreach ($target in @($python, $entry, $PSCommandPath)) {
        $expected = $settings.sourceHashes.PSObject.Properties[$target]
        if ($null -eq $expected -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected.Value) {
            throw 'A pinned backup dependency changed.'
        }
    }
    Write-Host 'Onoes-Mind / backup existing store' -ForegroundColor Cyan
    if ($settings.PSObject.Properties['archiveCredentialMode'] -and $settings.archiveCredentialMode -ceq 'windows-local') {
        Write-Host 'This encrypted archive uses your Windows account. No password entry is needed.'
    } else {
        Write-Host 'Use your saved BACKUP ARCHIVE password. This does not reset it.'
        Write-Host 'Enter it only in the hidden prompts below, never in chat.'
    }
    Write-Host ''
    & $python -I $entry --profile $Profile --sha $Sha --approval $Approval --run
    $backupExit = $LASTEXITCODE
    if ($backupExit -ne 0) {
        Write-Host 'Backup did not complete. Leave the files as they are for Nims; do not rerun.' -ForegroundColor Yellow
    } else {
        Write-Host 'Backup complete. Memory access and service settings are unchanged.' -ForegroundColor Green
    }
} catch {
    Write-Host 'Backup did not complete. Keep this window open for Nims. Do not rerun or share a password.' -ForegroundColor Yellow
} finally {
    Write-Host ''
    Write-Host 'This window will stay open until you close it.'
    while ((Read-Host 'Type CLOSE when you have read the final status') -cne 'CLOSE') { }
}
exit $backupExit

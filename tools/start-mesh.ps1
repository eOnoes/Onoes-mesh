param(
    [string]$DataDir = 'test/app03-mesh',
    [int]$PreviewPort = 4317
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $root '.runner'
$stateFile = Join-Path $stateDir 'mesh-serve.json'
if (Test-Path -LiteralPath $stateFile) {
    $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $existing = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($existing -and $existing.StartTime.ToUniversalTime().Ticks.ToString() -eq $state.startedTicks) {
        Write-Output "Mesh already running: $($state.previewUrl) (PID $($state.pid))"
        return
    }
}
$node = (Get-Command node.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$stdout = Join-Path $stateDir 'mesh-serve.log'
$stderr = Join-Path $stateDir 'mesh-serve-error.log'
$oldData = $env:MESH_DATA_DIR
$oldPort = $env:MESH_PREVIEW_PORT
try {
    $env:MESH_DATA_DIR = $DataDir
    $env:MESH_PREVIEW_PORT = "$PreviewPort"
    $child = Start-Process -FilePath $node -ArgumentList 'test/m1-serve.mjs' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
} finally {
    $env:MESH_DATA_DIR = $oldData
    $env:MESH_PREVIEW_PORT = $oldPort
}
try {
    $ready = $null
    $deadline = (Get-Date).AddSeconds(15)
    do {
        $child.Refresh()
        if ($child.HasExited) { throw "Mesh startup failed: $(Get-Content -LiteralPath $stderr -Raw)" }
        $line = Get-Content -LiteralPath $stdout | Select-Object -Last 1
        if ($line) {
            $ready = $line | ConvertFrom-Json
            if ($ready.event -eq 'mesh_listening') { break }
        }
        Start-Sleep -Milliseconds 100
    } while ((Get-Date) -lt $deadline)
    if (!$ready -or $ready.event -ne 'mesh_listening') { throw 'Mesh startup timed out.' }
    $proof = Invoke-WebRequest -Uri $ready.previewUrl -UseBasicParsing -TimeoutSec 5
    if ($proof.StatusCode -ne 200) { throw 'Mesh HTTP readiness failed.' }
    [ordered]@{ pid = $child.Id; startedTicks = $child.StartTime.ToUniversalTime().Ticks.ToString(); node = $node; url = $ready.url; previewUrl = $ready.previewUrl; dataDir = $ready.dataDir } | ConvertTo-Json | Set-Content -LiteralPath $stateFile
    Write-Output "Mesh: $($ready.previewUrl); backend: $($ready.url); PID $($child.Id)"
} catch {
    if (!$child.HasExited) { $child.Kill(); $child.WaitForExit(5000) | Out-Null }
    throw
}

<#
.SYNOPSIS
    Idempotent hidden launcher for the Onoes-Mesh Relay sandbox.

.DESCRIPTION
    Binds the Relay server on its exact loopback port with an exact identity check
    (executable, interpreter, working directory, data directory, port, and the process
    that is already listening). It refuses an unrelated listener rather than killing it,
    reuses a verified existing Relay owner instead of starting a second one, and never
    registers an OS startup item, scheduled task, or service.

    This launcher does NOT start or restart the production mesh on 8772 and never
    touches the unknown owner of 8771. Echo (the parent) owns production lifecycle.

.NOTES
    Owned by the relay-gaps worker. Reviewed build only — do not wire into a lifecycle
    until Echo has verified the receipt in .verification/RELAY-GAPS-FINAL-RESULT.md.
#>
[CmdletBinding()]
param(
    [int]$Port = 8772,
    [string]$Root = $PSScriptRoot,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

$ExpectedRoot = 'D:\Dev\Onoes-Mesh-sandbox'
$ExpectedData = Join-Path $ExpectedRoot 'data'
$ServerScript = Join-Path $Root 'server.py'
$PythonLauncher = (Get-Command python -ErrorAction SilentlyContinue).Source

function Write-Line($Text) { Write-Host $Text }

function Test-RelayIdentity {
    <# Returns a hashtable describing any listener already on the port, or $null. #>
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' } |
        Select-Object -First 1
    if (-not $listener) { return $null }

    $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if (-not $proc) {
        return @{ Port = $Port; Owner = $listener.OwningProcess; Verified = $false; Reason = 'no process for the listener' }
    }
    $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" |
        Select-Object -ExpandProperty CommandLine -ErrorAction SilentlyContinue)
    $isRelay = $cmdLine -and ($cmdLine -like "*server.py*") -and ($cmdLine -like "*$ExpectedRoot*")
    $isMesh = $cmdLine -and ($cmdLine -like "*8771*")
    return @{
        Port      = $Port
        Owner     = $listener.OwningProcess
        Name      = $proc.ProcessName
        CommandLine = $cmdLine
        Verified  = [bool]$isRelay
        IsSandboxMesh = [bool]$isMesh
        Reason    = if ($isRelay) { 'verified relay owner' } elseif ($isMesh) { 'the sandbox mesh on 8771' } else { 'unrelated listener' }
    }
}

# --- identity preflight --------------------------------------------------------------

if (-not (Test-Path -LiteralPath $ServerScript)) {
    Write-Line "refused: no server.py under $Root"
    exit 2
}
if (-not $PythonLauncher) {
    Write-Line 'refused: no python interpreter on PATH'
    exit 2
}
if (-not (Test-Path -LiteralPath $ExpectedData)) {
    Write-Line "refused: the Relay data directory is missing at $ExpectedData"
    exit 2
}
if ($Root -ne $ExpectedRoot) {
    Write-Line "refused: this launcher only serves $ExpectedRoot (got $Root)"
    exit 2
}

$existing = Test-RelayIdentity
if ($existing) {
    if ($existing.Verified) {
        Write-Line "already running: pid $($existing.Owner) on 127.0.0.1:$Port is the verified Relay owner. Nothing to do."
        exit 0
    }
    if ($existing.IsSandboxMesh) {
        Write-Line "refused: 127.0.0.1:$Port is held by the sandbox mesh (pid $($existing.Owner)). Relay lives on 8772; the mesh is not restarted here."
        exit 3
    }
    Write-Line "refused: 127.0.0.1:$Port is held by an unrelated listener (pid $($existing.Owner), $($existing.Name)). Not killed."
    exit 3
}

if ($CheckOnly) {
    Write-Line "ready: 127.0.0.1:$Port is free and $Root is the expected Relay root."
    exit 0
}

# --- launch -------------------------------------------------------------------------

# Use only the project-scoped, owner-approved Web Push dependencies when they exist.
# This does not install or enable delivery: keys, enrollment, and the one-use send
# capability remain separate fail-closed gates in relay_push.py.
$WebPushLib = Join-Path $ExpectedRoot '.webpush-lib'
if (Test-Path -LiteralPath $WebPushLib) {
    $env:PYTHONPATH = if ($env:PYTHONPATH) {
        "$WebPushLib;$($env:PYTHONPATH)"
    } else {
        $WebPushLib
    }
}
$env:MESH_SERVICE_TAG = 'onoes-mesh-relay'
$env:MESH_SERVICE_ROLE = 'relay'
$env:RELAY_STATE_DB = Join-Path $ExpectedData 'relay-state.db'
$psi = @{
    FilePath               = $PythonLauncher
    ArgumentList           = @('-B', $ServerScript, "$Port", '--mesh-service=onoes-mesh-relay', '--mesh-role=relay')
    WorkingDirectory       = $Root
    WindowStyle            = 'Hidden'
    PassThru               = $true
    NoNewWindow            = $true
}
$process = Start-Process @psi
Start-Sleep -Seconds 2
if ($process.HasExited) {
    Write-Line "failed: the Relay process exited with code $($process.ExitCode)."
    exit 4
}
$listener = Test-RelayIdentity
if (-not $listener -or -not $listener.Verified) {
    Write-Line 'failed: the port did not come up as the verified Relay owner.'
    exit 4
}
Write-Line "started: pid $($process.Id) on 127.0.0.1:$Port (hidden, verified identity)."
exit 0

param(
    [string]$NodePath = 'C:\Program Files\node.exe',
    [string]$EntryPath = (Join-Path $env:APPDATA 'npm\node_modules\@deepseek-ai\dsh\lib\bin.js'),
    [ValidateRange(1,65535)][int]$Port = 3081
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

function Save-LaunchState([string]$State, [object]$OwnedProcess = $null) {
    $record = [ordered]@{
        App = 'Onoes / DeepSeek Harness web'
        CheckedAt = [DateTime]::UtcNow.ToString('o')
        State = $State
        Host = '127.0.0.1'
        Port = $Port
    }
    if ($null -ne $OwnedProcess) {
        $record.ProcessId = $OwnedProcess.Id
        $record.StartedAt = $OwnedProcess.StartTime.ToUniversalTime().ToString('o')
        $record.Executable = $NodePath
        $record.Entrypoint = $EntryPath
    }
    $temporary = Join-Path $PSScriptRoot 'last-start.tmp'
    $destination = Join-Path $PSScriptRoot 'last-start.json'
    $record | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $destination -Force
}

function Test-LoopbackListener {
    $connection = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $connection.ConnectAsync('127.0.0.1', $Port)
        if (-not $pending.Wait(500)) { return $false }
        return $connection.Connected
    } catch {
        return $false
    } finally {
        $connection.Dispose()
    }
}

# Per-session singleton covers repeated launch requests while the server starts.
# An occupied port always wins; this script never stops an existing process.
$singleton = New-Object System.Threading.Mutex($false, ('Local\Onoes.DSH.Web.' + $Port))
$ownsSingleton = $false
try {
    try { $ownsSingleton = $singleton.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $ownsSingleton = $true }
    if (-not $ownsSingleton) { return }
    if (Test-LoopbackListener) {
        Save-LaunchState 'port-already-listening'
        return
    }
    if (-not (Test-Path -LiteralPath $NodePath -PathType Leaf)) { throw 'Node executable is missing.' }
    if (-not (Test-Path -LiteralPath $EntryPath -PathType Leaf)) { throw 'DSH web entrypoint is missing.' }
    if ($EntryPath.Contains('"')) { throw 'Invalid entrypoint path.' }
    $arguments = '"' + $EntryPath + '" web --host 127.0.0.1 --port ' + $Port + ' --no-open'
    $started = Start-Process -FilePath $NodePath -ArgumentList $arguments `
        -WorkingDirectory ([Environment]::GetFolderPath('UserProfile')) `
        -WindowStyle Hidden -PassThru
    Save-LaunchState 'process-started' $started
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $started.Refresh()
        if ($started.HasExited) { throw 'DSH exited before its web listener became ready.' }
        if (Test-LoopbackListener) {
            Save-LaunchState 'listener-ready' $started
            return $started
        }
        Start-Sleep -Milliseconds 500
    }
    Save-LaunchState 'started-listener-not-yet-ready' $started
    return $started
} catch {
    Save-LaunchState 'launch-failed'
    throw
} finally {
    if ($ownsSingleton) { $singleton.ReleaseMutex() }
    $singleton.Dispose()
}

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $root '.runner/mesh-serve.json'
if (!(Test-Path -LiteralPath $stateFile)) { Write-Output 'Mesh is already stopped.'; return }
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$child = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if ($child) {
    if ($child.StartTime.ToUniversalTime().Ticks.ToString() -ne $state.startedTicks -or $child.Path -ne $state.node) {
        throw 'Mesh process identity changed; no process stopped.'
    }
    Stop-Process -InputObject $child
    if (!$child.WaitForExit(5000)) { throw 'Mesh did not stop.' }
}
Remove-Item -LiteralPath $stateFile
Write-Output 'Mesh stopped; SQLite data retained.'

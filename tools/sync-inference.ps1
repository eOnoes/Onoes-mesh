# Collect Echo's PC inference telemetry into public/inference.json.
#
# Mesh's server only serves static files, so a collector writes a snapshot and the
# Control tab reads it - the same arrangement as the Relay agent and chat snapshots.
#
# Sources, in order of trust:
#
#   http://127.0.0.1:<port>/health     status, busy, loaded, model, max_context
#   http://127.0.0.1:<port>/props      n_ctx, engine binary, build info, model path
#   http://127.0.0.1:<port>/v1/models  context_length, vocab
#   nvidia-smi                         VRAM, utilisation, watts, temperature
#   the OS                             RAM, C: and D: fill
#
# Strata is reached through its wrapper, `unbiased-strata.exe`, which serves an
# OpenAI-compatible API and fronts the `strata-poly.exe` engine over stdio. The engine
# itself has no port, so the wrapper is the thing to ask.
#
# TPS / PPS / context-in-use / cost stay null. There is no /metrics, no /slots and no
# cumulative token counter on this build, so there is no request stream to time. Those
# numbers need either a proxy in front of the engine or per-request timings from the
# engine's own log. The snapshot says so rather than inventing a figure.
param(
  [string]$OutFile = "$PSScriptRoot\..\public\inference.json",
  [string]$HostName = "Echo's PC",
  [int[]]$Ports = @(60409, 8080, 1234, 8000)
)

$ErrorActionPreference = 'SilentlyContinue'

function Get-Gpu {
  $raw = & nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,power.draw,power.limit,temperature.gpu --format=csv,noheader,nounits 2>$null
  if (-not $raw) { return $null }
  $f = ($raw -split ',') | ForEach-Object { $_.Trim() }
  $used = [int]$f[1]; $total = [int]$f[2]
  return [ordered]@{
    name         = $f[0]
    vramUsedMiB  = $used
    vramTotalMiB = $total
    vramPct      = if ($total -gt 0) { [math]::Round(100.0 * $used / $total, 1) } else { $null }
    utilPct      = [int]$f[3]
    powerW       = [double]$f[4]
    powerLimitW  = [double]$f[5]
    tempC        = [int]$f[6]
  }
}

# Ask every candidate port until one answers /health like an inference server.
function Find-EngineApi {
  foreach ($port in $Ports) {
    try {
      $h = Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2
      if ($h -and $h.status) { return @{ port = $port; health = $h } }
    } catch { }
    try {
      $h = Invoke-RestMethod "http://127.0.0.1:$port/api/version" -TimeoutSec 2
      if ($h) { return @{ port = $port; health = $null; ollama = $h } }
    } catch { }
  }
  return $null
}

function Get-BaseModelShort([string]$name) {
  if (-not $name) { return $null }
  $n = $name
  $quant = if ($n -match '(Q\d[_A-Za-z0-9]*)') { $matches[1] } else { '' }
  $size  = if ($n -match '(\d+(?:\.\d+)?B-A\d+B)') { $matches[1] } elseif ($n -match '(\d+(?:\.\d+)?B)') { $matches[1] } else { '' }
  $first = ($n -split '[-_.]')[0]
  return (@($first, $size, $quant) | Where-Object { $_ }) -join ' '
}

$api = Find-EngineApi
$engine = $null
$ollama = [ordered]@{ running = $false; port = $null; modelsResident = 0 }

if ($api -and $api.health) {
  $health = $api.health
  $props = $null; $models = $null
  try { $props  = Invoke-RestMethod "http://127.0.0.1:$($api.port)/props" -TimeoutSec 3 } catch { }
  try { $models = Invoke-RestMethod "http://127.0.0.1:$($api.port)/v1/models" -TimeoutSec 3 } catch { }

  $alias = if ($props.model_alias) { $props.model_alias } else { $health.model }
  $ctx   = if ($props.default_generation_settings.n_ctx) { $props.default_generation_settings.n_ctx } else { $health.max_context }
  $owner = $null
  try { $owner = (Get-NetTCPConnection -LocalPort $api.port -State Listen | Select-Object -First 1).OwningProcess } catch { }
  $proc = if ($owner) { Get-CimInstance Win32_Process -Filter "ProcessId=$owner" } else { $null }

  $engine = [ordered]@{
    name        = if ($props.engine) { $props.engine } else { 'strata' }
    transport   = 'http'
    port        = $api.port
    loaded      = $health.loaded
    busy        = $health.busy
    modelAlias  = $alias
    modelShort  = Get-BaseModelShort $alias
    modelPath   = $props.model_path
    contextMax  = $ctx
    contextLength = if ($models.data[0].context_length) { $models.data[0].context_length } else { $null }
    buildInfo   = $props.build_info
    vocabSize   = $models.data[0].meta.n_vocab
    wrapper     = if ($proc) { ($proc.Name -replace '\.exe$','') } else { $null }
    wrapperPid  = $owner
    wrapperRamGB= if ($proc) { [math]::Round($proc.WorkingSetSize / 1GB, 2) } else { $null }
    startedAt   = if ($proc -and $proc.CreationDate) { ([datetime]$proc.CreationDate).ToString('o') } else { $null }
  }
} else {
  # No API: fall back to reading the engine's own command line.
  $proc = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match '\.gguf' } | Select-Object -First 1
  if ($proc) {
    $cl = [string]$proc.CommandLine
    $model = if ($cl -match '"([^"]+\.gguf)"') { $matches[1] } elseif ($cl -match '(\S+\.gguf)') { $matches[1] } else { $null }
    $ctx = if ($cl -match '--max-context\s+"?(\d+)"?') { [int]$matches[1] } else { $null }
    $engine = [ordered]@{
      name = ($proc.Name -replace '\.exe$',''); transport = 'stdio'; port = $null
      loaded = $true; busy = $null
      modelAlias = if ($model) { [System.IO.Path]::GetFileNameWithoutExtension(($model -split '\\')[-1]) } else { $null }
      modelShort = Get-BaseModelShort $model
      modelPath = $model; contextMax = $ctx; contextLength = $null
      buildInfo = $null; vocabSize = $null
      wrapper = $null; wrapperPid = $proc.ProcessId
      wrapperRamGB = [math]::Round($proc.WorkingSetSize / 1GB, 2)
      startedAt = if ($proc.CreationDate) { ([datetime]$proc.CreationDate).ToString('o') } else { $null }
    }
  }
}

try {
  $r = Invoke-RestMethod "http://127.0.0.1:11434/api/ps" -TimeoutSec 2
  $ollama.running = $true; $ollama.port = 11434
  $ollama.modelsResident = if ($r.models) { @($r.models).Count } else { 0 }
} catch { }

$os = Get-CimInstance Win32_OperatingSystem
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$freeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)

$disks = @()
foreach ($letter in @('C','D')) {
  $d = Get-PSDrive $letter -EA SilentlyContinue
  if ($d -and ($d.Used + $d.Free) -gt 0) {
    $cap = $d.Used + $d.Free
    $disks += [ordered]@{
      name = "${letter}:"; usedGB = [math]::Round($d.Used / 1GB, 1)
      totalGB = [math]::Round($cap / 1GB, 1); usedPct = [math]::Round(100.0 * $d.Used / $cap, 1)
    }
  }
}

$payload = [ordered]@{
  schema      = 'mesh-inference/v1'
  generatedAt = (Get-Date).ToString('o')
  host        = $HostName
  engine      = $engine
  ollama      = $ollama
  gpu         = Get-Gpu
  ram         = [ordered]@{
    totalGB = $totalGB; freeGB = $freeGB
    usedGB  = [math]::Round($totalGB - $freeGB, 1)
    usedPct = [math]::Round(100.0 * ($totalGB - $freeGB) / $totalGB, 1)
  }
  disks       = $disks
  throughput  = [ordered]@{
    tps = $null; pps = $null; contextUsed = $null; contextPct = $null
    reason = if ($engine -and $engine.transport -ne 'http') {
      'engine has no HTTP endpoint, so there is no request stream to time'
    } elseif ($engine -and $engine.busy -eq $false) {
      'engine is idle - no generation in flight to measure'
    } else { 'no request observed since this snapshot started' }
  }
  cost        = [ordered]@{
    simulatedUsd = $null
    reason = 'needs a token stream; run the engine behind a proxy to account usage'
  }
}

$dir = Split-Path $OutFile -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$payload | ConvertTo-Json -Depth 8 | Set-Content -Path $OutFile -Encoding utf8

if ($engine) {
  Write-Output ("inference: {0} via {1} :{2}  model={3}  ctx={4}  busy={5}" -f `
    $engine.name, $engine.transport, $engine.port, $engine.modelShort, $engine.contextMax, $engine.busy)
} else {
  Write-Output "inference: no engine found"
}

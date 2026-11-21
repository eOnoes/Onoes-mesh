# Read one Windows sensor sample. Emit JSON only, suitable for SSH stdout.
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$cpu = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'" -ErrorAction SilentlyContinue).PercentProcessorTime
$ram = if ($os.TotalVisibleMemorySize -gt 0) {
    [math]::Round(100 * (1 - $os.FreePhysicalMemory / $os.TotalVisibleMemorySize))
}
$gpuUse = $null
$gpuTemp = $null
$smi = Get-Command nvidia-smi.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($smi) {
    $lines = @(& $smi.Source '--query-gpu=utilization.gpu,temperature.gpu' '--format=csv,noheader,nounits' 2>$null)
    if ($LASTEXITCODE -eq 0 -and $lines.Count -eq 1) {
        $fields = $lines[0] -split ','
        if ($fields.Count -eq 2) {
            if ($fields[0].Trim() -match '^\d{1,3}$') { $gpuUse = [int]$fields[0].Trim() }
            if ($fields[1].Trim() -match '^\d{1,3}$') { $gpuTemp = [int]$fields[1].Trim() }
        }
    }
}
# Only report an actual CPU package sensor when LibreHardwareMonitor exposes one.
$packages = @(Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor -Filter "SensorType='Temperature'" -ErrorAction SilentlyContinue |
    Where-Object { $_.Identifier -match '^/(intelcpu|amdcpu)/' -and $_.Name -eq 'CPU Package' })
$cpuTemp = $null
if ($packages.Count -eq 1 -and $null -ne $packages[0].Value) { $cpuTemp = [double]$packages[0].Value }
[ordered]@{hostName=$env:COMPUTERNAME;cpuPct=$cpu;ramPct=$ram;gpuPct=$gpuUse;gpuTempC=$gpuTemp;cpuTempC=$cpuTemp} | ConvertTo-Json -Compress

# Compare this PC's registered TCP bindings with one Windows listener snapshot.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RegisterPath
)

$ErrorActionPreference = 'Stop'
$register = Get-Content -LiteralPath $RegisterPath -Raw | ConvertFrom-Json
if ($register.schema_version -ne 1) { throw 'Expected service register schema 1.' }
$hostName = [Environment]::MachineName
$bindings = @(foreach ($record in $register.records) {
    if ($record.host -ne $hostName) { continue }
    foreach ($binding in $record.bindings) {
        if ($binding.namespace -ne 'host' -or $binding.protocol -ne 'tcp') { continue }
        $address = [ipaddress]::Parse($binding.bind_address)
        $port = [int]$binding.port
        if ($port -lt 1 -or $port -gt 65535) { throw "Invalid port for $($record.service_id)." }
        [pscustomobject]@{ Service = $record.service_id; Address = $address; Port = $port
            PreviousPid = $record.pid_at_observation; RegisteredAs = $record.binding_status }
    }
})
if ($bindings.Count -eq 0) { throw "No registered host TCP bindings for $hostName." }

$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
foreach ($binding in $bindings) {
    $samePort = @($listeners | Where-Object LocalPort -eq $binding.Port)
    $matching = @($samePort | Where-Object { $binding.Address.Equals([ipaddress]$_.LocalAddress) })
    $owners = @($matching.OwningProcess | Where-Object { $null -ne $_ } | Sort-Object -Unique)
    $otherBinds = @($samePort | Where-Object { -not $binding.Address.Equals([ipaddress]$_.LocalAddress) } |
        ForEach-Object { ([Net.IPEndPoint]::new([ipaddress]$_.LocalAddress, $_.LocalPort)).ToString() } | Sort-Object -Unique)
    $alsoRegistered = @($bindings | Where-Object {
        $_.Service -ne $binding.Service -and $_.Port -eq $binding.Port -and $_.Address.Equals($binding.Address)
    } | Select-Object -ExpandProperty Service -Unique)
    $observation = if ($matching.Count -eq 0) {
        if ($otherBinds.Count) { 'Different address' } else { 'No listener' }
    } elseif ($owners.Count -ne 1 -or -not $binding.PreviousPid) {
        'Check owner'
    } elseif ($owners[0] -ne $binding.PreviousPid) {
        'PID changed'
    } else {
        'Same address and PID'
    }
    [pscustomobject]@{
        Service = $binding.Service
        Endpoint = ([Net.IPEndPoint]::new($binding.Address, $binding.Port)).ToString()
        Observation = $observation
        RegisteredPid = $binding.PreviousPid
        CurrentPids = $owners -join ', '
        OtherAddressesOnPort = $otherBinds -join ', '
        AlsoRegisteredTo = $alsoRegistered -join ', '
        RegisteredAs = $binding.RegisteredAs
    }
}

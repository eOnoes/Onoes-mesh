$ErrorActionPreference = 'Stop'
$check = Join-Path $PSScriptRoot '../tools/check-mesh-listeners.ps1'
$path = [IO.Path]::GetTempFileName()
$machine = [Environment]::MachineName
$failSnapshot = $false
function Record($service, $address, $port, $owner, $computer = $machine) {
    @{service_id=$service; host=$computer; pid_at_observation=$owner; binding_status='observed'
      bindings=@(@{namespace='host'; protocol='tcp'; bind_address=$address; port=$port})}
}
function Listener($address, $port, $owner) {
    [pscustomobject]@{LocalAddress=$address; LocalPort=$port; OwningProcess=$owner}
}
function Get-NetTCPConnection($State, $ErrorAction) {
    if ($State -ne 'Listen' -or $ErrorAction -ne 'Stop') { throw 'Expected a listener snapshot.' }
    if ($failSnapshot) { throw 'Fixture snapshot unavailable.' }
    Listener '0:0:0:0:0:0:0:1' 7001 101
    Listener '127.0.0.1' 7002 202
    Listener '0.0.0.0' 7003 303
    Listener '127.0.0.1' 7005 505
    Listener '127.0.0.1' 7006 601
    Listener '127.0.0.1' 7006 602
    Listener '127.0.0.1' 7007 707
    Listener '::1' 7007 707
}
try {
    $records = @(
        Record 'same' '::1' 7001 101
        Record 'changed' '127.0.0.1' 7002 201
        Record 'other-bind' '127.0.0.1' 7003 303
        Record 'absent' '127.0.0.1' 7004 404
        Record 'no-prior-owner' '127.0.0.1' 7005 $null
        Record 'multiple-owners' '127.0.0.1' 7006 601
        Record 'another-address' '127.0.0.1' 7007 707
        Record 'shared-endpoint' '0:0:0:0:0:0:0:1' 7001 101
        Record 'other-machine' '127.0.0.1' 7002 202 'other-pc'
    )
    @{schema_version=1;records=$records} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $path
    $original = (Get-FileHash -LiteralPath $path).Hash
    $rows = @(& $check -RegisterPath $path)
    $expected = @('Same address and PID','PID changed','Different address','No listener','Check owner','Check owner','Same address and PID','Same address and PID')
    if (($rows.Observation -join '|') -cne ($expected -join '|')) { throw 'Incorrect listener comparison.' }
    if ($rows[0].Endpoint -cne '[::1]:7001' -or $rows[1].CurrentPids -ne '202' -or
        $rows[2].OtherAddressesOnPort -ne '0.0.0.0:7003' -or $rows[5].CurrentPids -ne '601, 602' -or
        $rows[6].OtherAddressesOnPort -ne '[::1]:7007' -or $rows[0].AlsoRegisteredTo -ne 'shared-endpoint' -or
        $rows[7].AlsoRegisteredTo -ne 'same' -or $rows[1].AlsoRegisteredTo -or $rows[0].RegisteredAs -ne 'observed') {
        throw 'Incorrect address, owner or competing register details.'
    }
    $failSnapshot = $true
    try { & $check -RegisterPath $path; throw 'Failure reported as an empty snapshot.' }
    catch { if ($_.Exception.Message -ne 'Fixture snapshot unavailable.') { throw } }
    if ((Get-FileHash -LiteralPath $path).Hash -ne $original) { throw 'Register changed.' }
    'Passed local binding, owner, host isolation, IPv6, unavailable snapshot and read-only checks.'
} finally {
    Remove-Item -LiteralPath $path
}

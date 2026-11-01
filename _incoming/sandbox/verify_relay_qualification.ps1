# Explicit static or approved disposable Local8772 qualification.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Static', 'Local8772')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$PlanSha256,
    [int]$MaxLaunches = 2
)
$ErrorActionPreference = 'Stop'
$deadlineSeconds = 30.0
if ($Mode -ceq 'Local8772') { $deadlineSeconds = 156.0 }
$clock = [Diagnostics.Stopwatch]::StartNew()
$root = 'D:\Dev\Onoes-Mesh-sandbox'
$receipt = Join-Path $root '.verification/RELAY-QUALIFICATION-PHASE-C-IMPLEMENTATION.md'
$approved = '694d40edf4d25cda9a4f1963d3bb4db0b8786d91dfea48b2a806059862760ec1'
$auditHash = '163400a5bd32e7be3312cb8afff9c8b62ea405c92d79f3a2cb8b74e30a829ed7'
$qualificationHash = '2e4699a33628b1e9ddca55a414f7b57bfb3f8e9c575c8bc2382d07afc536cb18'
$runnerHash = '4488c54bf087dc57292a7735247649463ce5e2d540a10168fc8f3d301d8940a2'
$process = $null
$timedOut = $false
$cleanupRequested = $false
$holderRetained = $false
$cleanMarker = 'CUSTODY_CLEAN child_exits_confirmed root_removed no_8772_listener'
$captured = [Text.StringBuilder]::new()
$stderr = [Text.StringBuilder]::new()
$capturedBytes = 0
$utf8 = [Text.UTF8Encoding]::new($false, $true)

function Assert-Deadline {
    if ($clock.Elapsed.TotalSeconds -ge $deadlineSeconds) {
        $script:timedOut = $true
        throw "$Mode complete command exceeded $deadlineSeconds seconds"
    }
}

function Append-Receipt([string]$Text) {
    if (-not (Test-Path -LiteralPath $receipt -PathType Leaf)) { throw 'Existing receipt absent' }
    $before = [IO.File]::ReadAllBytes($receipt)
    $section = '## Local8772 wrapper-repair continuation (2026-10-13)'
    if (-not $utf8.GetString($before).Contains($section)) { $Text = "`n`n$section`n`n" + $Text }
    $bytes = $utf8.GetBytes($Text)
    $stream = [IO.FileStream]::new($receipt, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    $after = [IO.File]::ReadAllBytes($receipt)
    if ($after.Length -ne $before.Length + $bytes.Length -or
        [Convert]::ToBase64String($after, 0, $before.Length) -cne [Convert]::ToBase64String($before) -or
        [Convert]::ToBase64String($after, $before.Length, $bytes.Length) -cne [Convert]::ToBase64String($bytes)) { throw 'Receipt append read-back mismatch' }
}

try {
    if ($Mode -cnotin @('Static', 'Local8772')) { throw 'Exact explicit mode required' }
    if ($Mode -ceq 'Local8772' -and $MaxLaunches -ne 2) { throw 'Local8772 requires MaxLaunches exactly 2' }
    if ((Get-Location).Path -cne $root -or $PSScriptRoot -cne $root) { throw 'Repository root mismatch' }
    if ($PlanSha256 -cne $approved) { throw 'Approved plan hash mismatch' }
    $planPath = Join-Path $root '.verification/RELAY-QUALIFICATION-PHASE-C-PLAN.md'
    $auditPath = Join-Path $root '.verification/RELAY-QUALIFICATION-PHASE-C-PLAN-CODEX.md'
    if ((Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $approved) { throw 'Plan content hash mismatch' }
    if ((Get-FileHash -LiteralPath $auditPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $auditHash) { throw 'Audit content hash mismatch' }
    if ((git -C $root rev-parse HEAD) -cne '3ce7b4fc929308ce5a0a998bb40ce965cf365202' -or $LASTEXITCODE -ne 0) { throw 'Baseline HEAD mismatch' }
    $protected = [regex]::Matches([IO.File]::ReadAllText($planPath, $utf8), '(?m)^\| ([^|]+?) \| `([0-9a-f]{64})` \|\r?$')
    if ($protected.Count -ne 21) { throw 'Protected manifest count mismatch' }
    foreach ($entry in $protected) {
        if ((Get-FileHash -LiteralPath (Join-Path $root $entry.Groups[1].Value) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.Groups[2].Value) { throw ('Protected hash mismatch: ' + $entry.Groups[1].Value) }
    }
    if (-not (Test-Path -LiteralPath $receipt -PathType Leaf)) { throw 'Existing receipt absent' }
    $history = [IO.File]::ReadAllBytes($receipt)
    if ($history.Length -lt 14157 -or $history.Length -gt 262144) { throw 'Receipt length invalid' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $prefixHash = [BitConverter]::ToString($sha.ComputeHash($history, 0, 14157)).Replace('-', '').ToLowerInvariant() } finally { $sha.Dispose() }
    if ($prefixHash -cne '2be9a2d45f0c16f70b4e973bfa4f989c2bb927b76b70f6fe5233dffdee41d123') { throw 'Historical receipt prefix changed' }
    if (-not [IO.Path]::IsPathRooted($Python)) { throw 'Python must be an absolute interpreter path' }
    $resolvedPython = (Resolve-Path -LiteralPath $Python).Path
    if ($resolvedPython -cne $Python) { throw 'Interpreter path must be canonical' }
    $ancestor = Get-Item -LiteralPath $resolvedPython
    while ($null -ne $ancestor) {
        if (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Interpreter ancestry contains reparse point' }
        if ($ancestor -is [IO.FileInfo]) { $ancestor = $ancestor.Directory } else { $ancestor = $ancestor.Parent }
    }
    $pythonHash = (Get-FileHash -LiteralPath $resolvedPython -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($resolvedPython -cne 'C:\Users\eMitchell109\AppData\Local\hermes\tools\python-3.14.7+20260901-win32-x64\python.exe' -or $pythonHash -cne '703536cd5d48b90407300079f490247e81244057652895d5a60df1e7d2991962') { throw 'Approved interpreter path/hash mismatch' }
    $sourcePaths = @('relay_qualification.py', 'test_relay_qualification.py', 'verify_relay_qualification.ps1')
    $sourceEvidence = [Text.StringBuilder]::new()
    foreach ($path in $sourcePaths) {
        $full = Join-Path $root $path
        $item = Get-Item -LiteralPath $full
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.Length -gt 131072) { throw "Source path/size invalid: $path" }
        $hash = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($path -ceq 'relay_qualification.py' -and $hash -cne $qualificationHash) { throw 'Qualification source hash mismatch' }
        if ($path -ceq 'test_relay_qualification.py' -and $hash -cne $runnerHash) { throw 'Runner source hash mismatch' }
        $text = [IO.File]::ReadAllText($full, $utf8)
        if (-not $text.EndsWith("`n") -or $text.Contains("`t") -or [regex]::IsMatch($text, '(?m)[ \t]+\r?$')) { throw "Direct whitespace check failed: $path" }
        [void]$sourceEvidence.AppendLine("$path SHA-256 $hash")
    }
    $runner = Join-Path $root 'test_relay_qualification.py'
    $argv = @('-I', '-S', '-B', $runner, '--static', '--plan-sha256', $approved)
    if ($Mode -ceq 'Local8772') { $argv = @('-I', '-S', '-B', $runner, '--local-8772', '--plan-sha256', $approved, '--max-launches', '2') }
    $rendered = '"' + $resolvedPython + '" ' + (($argv | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    if ($rendered.Length -ge 4096 -or $resolvedPython.Contains('"') -or $runner.Contains('"')) { throw 'Argv contract exceeds bound/invalid quoting' }
    Assert-Deadline
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $resolvedPython
    $info.Arguments = (($argv | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    $info.WorkingDirectory = $root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.RedirectStandardInput = $true
    $info.Environment.Clear()
    $info.Environment['SystemRoot'] = [Environment]::GetEnvironmentVariable('SystemRoot')
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    if (-not $process.Start()) { throw "$Mode runner start failed" }
    $retainedHandle = $process.Handle
    $outBuffer = [char[]]::new(2048)
    $errBuffer = [char[]]::new(2048)
    $outRead = $process.StandardOutput.ReadAsync($outBuffer, 0, $outBuffer.Length)
    $errRead = $process.StandardError.ReadAsync($errBuffer, 0, $errBuffer.Length)
    $outDone = $false
    $errDone = $false
    while (-not ($process.HasExited -and $outDone -and $errDone)) {
        if ($Mode -ceq 'Local8772' -and $clock.Elapsed.TotalSeconds -ge 150.0) {
            $timedOut = $true
            throw 'Local8772 active budget exhausted; bounded owned cleanup required'
        }
        Assert-Deadline
        if (-not $outDone -and $outRead.IsCompleted) {
            $count = $outRead.GetAwaiter().GetResult()
            if ($count -eq 0) { $outDone = $true } else {
                $part = [string]::new($outBuffer, 0, $count)
                $capturedBytes += $utf8.GetByteCount($part)
                if ($capturedBytes -gt 1048576) { throw 'Captured stdout/stderr exceeds 1 MiB' }
                [void]$captured.Append($part)
                $outRead = $process.StandardOutput.ReadAsync($outBuffer, 0, $outBuffer.Length)
            }
        }
        if (-not $errDone -and $errRead.IsCompleted) {
            $count = $errRead.GetAwaiter().GetResult()
            if ($count -eq 0) { $errDone = $true } else {
                $part = [string]::new($errBuffer, 0, $count)
                $capturedBytes += $utf8.GetByteCount($part)
                if ($capturedBytes -gt 1048576) { throw 'Captured stdout/stderr exceeds 1 MiB' }
                [void]$stderr.Append($part)
                $errRead = $process.StandardError.ReadAsync($errBuffer, 0, $errBuffer.Length)
            }
        }
        [Threading.Thread]::Sleep(5)
    }
    $exitCode = $process.ExitCode
    if ($exitCode -ne 0 -or $stderr.Length -ne 0) { throw "$Mode runner failed: exit=$exitCode stderr-bytes=$($utf8.GetByteCount($stderr.ToString()))" }
    $result = 'RESULT mode=static cases=16 pass=16 fail=0 skip=0 not_run=0 violations=0'
    $pattern = '^' + [regex]::Escape($result) + '\r?$'
    $casePattern = '(?m)^C([0-9]{2}) PASS static '
    if ($Mode -ceq 'Local8772') {
        $result = 'RESULT mode=local-8772 cases=16 pass=16 fail=0 skip=0 not_run=0 violations=0 launches=2'
        $pattern = '^' + [regex]::Escape($result) + '(?: requests=(?:[0-9]|[1-5][0-9]|6[0-4]))?\r?$'
        $casePattern = '(?m)^C([0-9]{2}) PASS '
        if ([regex]::Matches($captured.ToString(), '(?m)^' + [regex]::Escape($cleanMarker) + '\r?$').Count -ne 1) { throw 'Local8772 clean custody marker mismatch' }
    }
    $results = [regex]::Matches($captured.ToString(), '(?m)^RESULT .*\r?$')
    $cases = [regex]::Matches($captured.ToString(), $casePattern)
    if ($results.Count -ne 1 -or -not [regex]::IsMatch($results[0].Value, $pattern) -or $cases.Count -ne 16 -or
        [regex]::IsMatch($captured.ToString(), '(?m)^(?:BLOCKED|UNKNOWN_CUSTODY)')) { throw "$Mode result/count contract mismatch" }
    for ($i = 0; $i -lt 16; $i++) {
        if ($cases[$i].Groups[1].Value -cne ($i + 1).ToString('D2')) { throw "$Mode case order mismatch" }
    }
    Assert-Deadline
    $elapsed = $clock.Elapsed.TotalSeconds.ToString('F3', [Globalization.CultureInfo]::InvariantCulture)
    $record = "`n### $Mode wrapper observation`n`n"
    $record += "Focused runner succeeded; final independent gates pending. Local evidence is disposable fixture rehearsal only; no production, real Hermes, phone/PWA, deployment, Mind or release readiness.`n`n"
    $record += "Exact argv: $rendered`nInterpreter SHA-256: $pythonHash`nPlan SHA-256: $approved`nAudit SHA-256: $auditHash`n"
    $record += $sourceEvidence.ToString() + "Exit=$exitCode; timeout=0; elapsed-before-receipt=${elapsed}s; capture-bytes=$capturedBytes; stdout/stderr bound=1048576; complete deadline=${deadlineSeconds}s. Original wrapper handle retained. Protected hashes: 21/21 pass.`n"
    $record += "Direct whitespace: 3/3 pass. Static evidence is declarations/AST/text/hash/in-memory compilation only; local output labels native and synthetic evidence separately.`n`n" + '```text' + "`n" + $captured.ToString() + '```' + "`n"
    Append-Receipt $record
    Assert-Deadline
    Write-Output $captured.ToString().TrimEnd()
    Write-Output ("WRAPPER exit=0 timeout=0 elapsed=" + $clock.Elapsed.TotalSeconds.ToString('F3', [Globalization.CultureInfo]::InvariantCulture) + 's receipt=append-only')
} catch {
    $detail = $_.Exception.Message
    if ($detail.Length -gt 4096) { $detail = $detail.Substring(0, 4096) }
    if ($null -ne $process -and -not $process.HasExited) {
        Write-Output ("BLOCKED " + $detail)
        if ($Mode -ceq 'Local8772') {
            $cleanupRequested = $true
            $cleanupUntil = [Math]::Min($clock.Elapsed.TotalSeconds + 6.0, $deadlineSeconds - 0.5)
            try {
                $frame = '{"command":"cleanup","plan":"' + $approved + '"}'
                $send = $process.StandardInput.WriteLineAsync($frame)
                while (-not $send.IsCompleted -and $clock.Elapsed.TotalSeconds -lt $cleanupUntil) { [Threading.Thread]::Sleep(5) }
                if ($send.IsCompleted) { $send.GetAwaiter().GetResult() }
                while ($clock.Elapsed.TotalSeconds -lt $cleanupUntil -and -not ($process.HasExited -and $outDone -and $errDone)) {
                    foreach ($pipe in @('out', 'err')) {
                        $read = if ($pipe -ceq 'out') { $outRead } else { $errRead }
                        $done = if ($pipe -ceq 'out') { $outDone } else { $errDone }
                        if (-not $done -and $null -ne $read -and $read.IsCompleted) {
                            $count = $read.GetAwaiter().GetResult()
                            if ($count -eq 0) {
                                if ($pipe -ceq 'out') { $outDone = $true } else { $errDone = $true }
                            } else {
                                $buffer = if ($pipe -ceq 'out') { $outBuffer } else { $errBuffer }
                                $part = [string]::new($buffer, 0, $count)
                                $capturedBytes += $utf8.GetByteCount($part)
                                if ($capturedBytes -gt 1048576) { throw 'Cleanup capture exceeds 1 MiB' }
                                if ($pipe -ceq 'out') {
                                    [void]$captured.Append($part)
                                    $outRead = $process.StandardOutput.ReadAsync($outBuffer, 0, $outBuffer.Length)
                                } else {
                                    [void]$stderr.Append($part)
                                    $errRead = $process.StandardError.ReadAsync($errBuffer, 0, $errBuffer.Length)
                                }
                            }
                        }
                    }
                    [Threading.Thread]::Sleep(5)
                }
            } catch { $detail += '; cleanup transport: ' + $_.Exception.Message }
            $clean = [regex]::IsMatch($captured.ToString(), '(?m)^' + [regex]::Escape($cleanMarker) + '\r?$')
            if (-not $process.HasExited -and $clean) { $process.Kill(); [void]$process.WaitForExit(250) }
            $holderRetained = -not $process.HasExited
        } else {
            # Only the retained static command handle.
            $process.Kill()
            [void]$process.WaitForExit(250)
        }
    }
    $failure = "`n### BLOCKED ($Mode wrapper)`n`nError: $detail`nTimeout=$timedOut; cleanup-requested=$cleanupRequested; custody-holder-retained=$holderRetained. Stop; no qualification success claim.`n"
    if ($captured.Length -ne 0 -or $stderr.Length -ne 0) { $failure += '```text' + "`n" + $captured.ToString() + $stderr.ToString() + "`n" + '```' + "`n" }
    Append-Receipt $failure
    Write-Output ("BLOCKED " + $detail)
    exit 1
} finally {
    if ($null -ne $process -and -not $holderRetained) { $process.Dispose() }
}

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, realpathSync, readFileSync, copyFileSync } from 'node:fs';
import { resolve, join, dirname, basename } from 'node:path';
import { createServer } from 'node:net';
import { execFileSync } from 'node:child_process';

test('Relay launch custody checks real file inputs, identity, receipt roundtrip and explicit environment without leaking secrets', {skip:process.platform!=='win32'},()=>{
  const data=realpathSync(resolve('data')),root=mkdtempSync(join(data,'relay-binding-fixture-'));
  mkdirSync(join(root,'.venv','Scripts'),{recursive:true});
  writeFileSync(join(root,'.venv','Scripts','pythonw.exe'),'fixture executable');
  writeFileSync(join(root,'base-pythonw.exe'),'fixture base executable');
  const files=['relay_server.py','relay_a2a.py','relay_a2a_reconcile.py','relay_auth.py','relay_budget.py','relay_channels.py',
    'relay_config.py','relay_db.py','relay_hermes.py','relay_inbox.py','relay_mcp.py','relay_native_receipts.py','relay_notify.py','relay_openclaw.py','relay_sessions.py','relay_webpush.py'];
  for(const file of files)writeFileSync(join(root,file),'# disposable fixture\n');
  writeFileSync(join(root,'.venv','pyvenv.cfg'),'home = fixture\n');
  writeFileSync(join(root,'launcher.ps1'),'# disposable launcher\n');
  writeFileSync(join(root,'config.json'),JSON.stringify({agents:{dsh:{backend:'a2a',url:'http://PRIVATE_ROUTE_SECRET'},cyony:{backend:'a2a',url:'http://elsewhere'}},api_key:'PRIVATE_CONFIG_SECRET'}));
  const script=String.raw`
$ErrorActionPreference='Stop'
. $env:MESH_RELAY_BINDING_HELPER
$root=$env:MESH_RELAY_BINDING_FIXTURE
$launcher=Join-Path $root 'launcher.ps1'
$helper=$env:MESH_RELAY_BINDING_HELPER
$basePython=Join-Path $root 'base-pythonw.exe'
$env:RELAY_CONFIG_PATH=$null;$env:RELAY_SESSION_DB=$null;$env:RELAY_SKIP_OPENCLAW=$null
$env:RELAY_FIXTURE_SECRET='PRIVATE_ENVIRONMENT_SECRET'
Assert-RelayLaunchEnvironment $root
$inputs=Get-RelayLaunchInputs $root $launcher $helper $basePython
$again=Get-RelayLaunchInputs $root $launcher $helper $basePython
if($inputs.Digest -ne $again.Digest){throw 'Non-deterministic input digest'}
$json=$inputs | ConvertTo-Json -Depth 12 -Compress
foreach($secret in @('PRIVATE_ROUTE_SECRET','PRIVATE_CONFIG_SECRET','PRIVATE_ENVIRONMENT_SECRET')){if($json.Contains($secret)){throw 'Input evidence leaked secret'}}
$rootProcess=[pscustomobject]@{ProcessId=40;ParentProcessId=1;ExecutablePath='fixture-pythonw';CreationDate=[datetime]'2020-01-01T00:00:00Z';CommandLine='fixture relay_server.py'}
$listener=[pscustomobject]@{ProcessId=41;ParentProcessId=40;ExecutablePath='fixture-base-pythonw';CreationDate=[datetime]'2020-01-01T00:00:01Z';CommandLine='fixture relay_server.py'}
$receipt=[pscustomobject]@{Schema='onoes-owned-process/v1';Id=40;RuntimeBinding=[pscustomobject]@{
 Schema='onoes-relay-runtime-binding/v1';Stable=$true;Inputs=$inputs;Root=Get-RelayProcessIdentity $rootProcess;Listener=Get-RelayProcessIdentity $listener}}
$results=@()
function Check($expected,$record,$processes,$listenerId,$current){
 $result=Test-RelayLaunchBinding $record $processes $listenerId $current
 if($result.State -ne $expected -or $result.CanRelease -or $result.LoadedBytesAttested){throw ('Unexpected custody: '+$result.State)}
 $script:results+=@($result.State)
}
Check 'matched_observed_launch_inputs' $receipt @($rootProcess,$listener) 41 $inputs
$roundtrip=$receipt | ConvertTo-Json -Depth 12 | ConvertFrom-Json
Check 'matched_observed_launch_inputs' $roundtrip @($rootProcess,$listener) 41 $inputs
$corrupt=$receipt | ConvertTo-Json -Depth 12 | ConvertFrom-Json;$corrupt.RuntimeBinding.Inputs.Evidence.Routes[0].Backend='hermes'
Check 'unverified_receipt_input_digest' $corrupt @($rootProcess,$listener) 41 $inputs
Check 'unverified_legacy_or_missing_receipt' ([pscustomobject]@{Schema='onoes-owned-process/v1';Id=40}) @($rootProcess,$listener) 41 $inputs
Check 'unverified_legacy_or_missing_receipt' $null @($rootProcess,$listener) 41 $inputs
Check 'unverified_process_missing' $receipt @($listener) 41 $inputs
$reused=$rootProcess | Select-Object *;$reused.CreationDate=[datetime]'2020-01-02T00:00:00Z'
Check 'unverified_process_identity' $receipt @($reused,$listener) 41 $inputs
$otherListener=$listener | Select-Object *;$otherListener.ParentProcessId=99
$wrong=$receipt | ConvertTo-Json -Depth 12 | ConvertFrom-Json
$wrong.RuntimeBinding.Listener=Get-RelayProcessIdentity $otherListener
Check 'unverified_process_identity' $wrong @($rootProcess,$otherListener) 41 $inputs
$unstable=$receipt | ConvertTo-Json -Depth 12 | ConvertFrom-Json;$unstable.RuntimeBinding.Stable=$false
Check 'unverified_unstable_launch' $unstable @($rootProcess,$listener) 41 $inputs
Add-Content -LiteralPath (Join-Path $root 'relay_server.py') -Value '# changed source'
$changed=Get-RelayLaunchInputs $root $launcher $helper $basePython
Check 'unverified_launch_inputs_changed' $receipt @($rootProcess,$listener) 41 $changed
$env:RELAY_FIXTURE_SECRET='a different fixture value'
$changedEnv=Get-RelayLaunchInputs $root $launcher $helper $basePython
if($changed.Digest -eq $changedEnv.Digest){throw 'Environment inputs were not fingerprinted'}
$env:RELAY_CONFIG_PATH='C:\unexpected-config.json';$rejected=$false
try{Assert-RelayLaunchEnvironment $root}catch{$rejected=$true}
if(!$rejected){throw 'Unexpected config selector accepted'}
$env:RELAY_CONFIG_PATH=Join-Path $root 'config.json'
$env:RELAY_SESSION_DB=Join-Path $root '.private\relay.sqlite3'
Assert-RelayLaunchEnvironment $root
$env:RELAY_SKIP_OPENCLAW='1';$rejected=$false
try{Assert-RelayLaunchEnvironment $root}catch{$rejected=$true}
if(!$rejected){throw 'Adapter skipping accepted'}
[pscustomobject]@{Cases=$results.Count;States=$results;SecretsExcluded=$true;SelectorAndAdapterChecks=$true;SourceAndEnvironmentDrift=$true} | ConvertTo-Json -Depth 8 -Compress
`;
  try{
    const output=execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,encoding:'utf8',timeout:20000,
      env:{...process.env,MESH_RELAY_BINDING_FIXTURE:root,MESH_RELAY_BINDING_HELPER:resolve('integrations/relay-runtime-binding.ps1')}});
    const result=JSON.parse(output.trim());assert.equal(result.Cases,10);assert.equal(result.SecretsExcluded,true);
    assert.equal(result.SelectorAndAdapterChecks,true);assert.equal(result.SourceAndEnvironmentDrift,true);
  }finally{
    const actual=realpathSync(root);assert.equal(dirname(actual),data);assert.ok(basename(actual).startsWith('relay-binding-fixture-'));
    rmSync(actual,{recursive:true,force:true});
  }
});

test('the unchanged Relay launcher algorithm captures a real owned fixture process and never adopts/restarts an existing one', {skip:process.platform!=='win32'},async()=>{
  const data=realpathSync(resolve('data')),root=mkdtempSync(join(data,'relay-launch-fixture-'));
  const portOwner=createServer();await new Promise(done=>portOwner.listen(0,'127.0.0.1',done));
  const port=portOwner.address().port;await new Promise(done=>portOwner.close(done));
  assert.ok(![3081,4123,4320,8452,8453,8642,8787].includes(port));
  const relay=join(root,'relay'),scripts=join(root,'mesh','integrations');
  mkdirSync(join(relay,'.venv','Scripts'),{recursive:true});mkdirSync(join(relay,'.private'));mkdirSync(scripts,{recursive:true});
  copyFileSync('C:/Python314/pythonw.exe',join(relay,'.venv','Scripts','pythonw.exe'));
  writeFileSync(join(relay,'.venv','pyvenv.cfg'),'home = C:\\Python314\n');
  writeFileSync(join(relay,'.private','relay.key'),'synthetic-key');
  const names=['relay_a2a.py','relay_a2a_reconcile.py','relay_auth.py','relay_budget.py','relay_channels.py','relay_config.py',
    'relay_db.py','relay_hermes.py','relay_inbox.py','relay_mcp.py','relay_native_receipts.py','relay_notify.py','relay_openclaw.py','relay_sessions.py','relay_webpush.py'];
  for(const name of names)writeFileSync(join(relay,name),'# synthetic module\n');
  writeFileSync(join(relay,'config.json'),JSON.stringify({port,agents:{dsh:{backend:'a2a',url:'http://fixture'},cyony:{backend:'a2a',url:'http://fixture'}}}));
  writeFileSync(join(relay,'relay_server.py'),`from http.server import HTTPServer,BaseHTTPRequestHandler\nclass H(BaseHTTPRequestHandler):\n def log_message(self,*a):pass\n def do_GET(self):\n  self.send_response(200);self.end_headers();self.wfile.write(b'fixture')\nHTTPServer(('127.0.0.1',${port}),H).serve_forever()\n`);
  copyFileSync('integrations/relay-runtime-binding.ps1',join(scripts,'relay-runtime-binding.ps1'));
  // Only deployment constants differ: source/config logic and all guards are kept.
  const original=readFileSync('integrations/relay-service.ps1','utf8');
  const fixture=original.replace("$relayRoot='D:\\Dev\\Onoes-Relay'",'$relayRoot=$env:MESH_RELAY_CAPTURE_ROOT')
    .replace("$python=Join-Path $relayRoot '.venv\\Scripts\\pythonw.exe'","$python='C:\\Python314\\pythonw.exe'")
    .replaceAll('8787',String(port)).replace('Local\\ONOesMeshRelayStart','Local\\OnoesRelayCapture'+port);
  assert.notEqual(fixture,original);assert.ok(!fixture.includes("$relayRoot='D:\\Dev\\Onoes-Relay'"));
  writeFileSync(join(scripts,'relay-service.ps1'),fixture);
  const script=String.raw`
$ErrorActionPreference='Stop'
$env:RELAY_CONFIG_PATH=$null;$env:RELAY_SESSION_DB=$null;$env:RELAY_SKIP_OPENCLAW=$null
$owned=$null
try {
 $first=. $env:MESH_RELAY_CAPTURE_LAUNCHER -Action Start | Out-String | ConvertFrom-Json
 $owned=$started
 if(!$owned -or !$first.Healthy -or $first.LaunchBinding.State -ne 'matched_observed_launch_inputs'){throw ('Fresh fixture binding failed: '+($first | ConvertTo-Json -Depth 8 -Compress))}
 $firstId=$first.ListenerId
 $second=. $env:MESH_RELAY_CAPTURE_LAUNCHER -Action Start | Out-String | ConvertFrom-Json
 if($second.ListenerId -ne $firstId -or $started.Id -ne $owned.Id){throw 'Second Start replaced the owned fixture'}
 Add-Content -LiteralPath (Join-Path $env:MESH_RELAY_CAPTURE_ROOT 'relay_a2a.py') -Value '# drift'
 $drift=. $env:MESH_RELAY_CAPTURE_LAUNCHER -Action Status | Out-String | ConvertFrom-Json
 if(!$drift.Healthy -or $drift.ListenerId -ne $firstId -or $drift.LaunchBinding.State -ne 'unverified_launch_inputs_changed'){throw 'Source drift not reported on same healthy process'}
 [pscustomobject]@{FreshLaunchCaptured=$true;SecondStartUnchanged=$true;DriftDetected=$true;LoadedBytesAttested=$first.LaunchBinding.LoadedBytesAttested;CanRelease=$first.LaunchBinding.CanRelease} | ConvertTo-Json -Compress
} finally {
 if(!$owned -and $started){$owned=$started}
 if($owned -and !$owned.HasExited){$owned.Kill();if(!$owned.WaitForExit(5000)){throw 'Owned fixture did not exit'}}
}
`;
  try{
    const output=execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,encoding:'utf8',timeout:30000,
      env:{...process.env,MESH_RELAY_CAPTURE_ROOT:relay,MESH_RELAY_CAPTURE_LAUNCHER:join(scripts,'relay-service.ps1')}});
    const result=JSON.parse(output.trim());assert.equal(result.FreshLaunchCaptured,true);assert.equal(result.SecondStartUnchanged,true);assert.equal(result.DriftDetected,true);
    assert.equal(result.LoadedBytesAttested,false);assert.equal(result.CanRelease,false);
  }finally{
    const actual=realpathSync(root);assert.equal(dirname(actual),data);assert.ok(basename(actual).startsWith('relay-launch-fixture-'));
    rmSync(actual,{recursive:true,force:true,maxRetries:5,retryDelay:100});
  }
});

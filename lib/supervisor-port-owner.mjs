import {execFile} from 'node:child_process';
import {promisify} from 'node:util';

export const SUPERVISOR_MODEL_PORTS=Object.freeze([8098,8099,18090,18091]);
const ENTRY='D:\\DeepSeekHarness-TestingGrounds\\Qwen3.8-Flash Testing\\local-models\\local_supervisor.py';
const SOURCE_SHA='f824f638777db226c1d4f00cc37fc7849ae0ab3c1def5a234b4a639598b73786';
const MODULE_SHA='7b823cd6a07fad21c7471142e999e3122d26c880cfbcd9c0f4acfe8cc6874116';
const run=promisify(execFile);

export function isQualifiedSupervisorOwner(value) {
  if(!value||!Number.isSafeInteger(value.pid)||value.pid<=0||
    typeof value.executable!=='string'||typeof value.commandLine!=='string'||
    !['C:\\Python314\\python.exe','C:\\Python314\\pythonw.exe'].some(p=>p.toLowerCase()===value.executable?.toLowerCase())||
    ![`"${value.executable}" "${ENTRY}"`,`${value.executable} "${ENTRY}"`].some(c=>c.toLowerCase()===value.commandLine?.toLowerCase())||
    value.sourceSha256!==SOURCE_SHA||value.moduleSha256!==MODULE_SHA)return false;
  const start=Date.parse(value.createdAt),source=Date.parse(value.sourceModifiedAt),module=Date.parse(value.moduleModifiedAt);
  if(![start,source,module].every(t=>Number.isFinite(t)&&t>0)||source>start||module>start)return false;
  const rows=value.listeners;
  return Array.isArray(rows)&&rows.length===4&&SUPERVISOR_MODEL_PORTS.every(port=>
    rows.filter(row=>row.port===port&&row.address==='127.0.0.1'&&row.pid===value.pid).length===1);
}

// Inspect Windows ownership before any HTTP request: another manager may autoload
// on an ordinary /health or /v1/models request. Never inspect process environments.
const SCRIPT=String.raw`$ErrorActionPreference='Stop'
$ports=@(8098,8099,18090,18091)
$rows=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue|Where-Object {$_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -in $ports})
$owners=@($rows.OwningProcess|Select-Object -Unique)
if($rows.Count -ne 4 -or $owners.Count -ne 1){'{}';exit 0}
$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$owners[0])
if(!$p){'{}';exit 0}
$entry='D:\DeepSeekHarness-TestingGrounds\Qwen3.8-Flash Testing\local-models\local_supervisor.py'
$module=Join-Path (Split-Path $entry) 'supervisor_mesh_control.py'
@{pid=[int]$p.ProcessId;executable=$p.ExecutablePath;commandLine=$p.CommandLine;createdAt=$p.CreationDate.ToUniversalTime().ToString('o');sourceSha256=(Get-FileHash -LiteralPath $entry -Algorithm SHA256).Hash.ToLowerInvariant();moduleSha256=(Get-FileHash -LiteralPath $module -Algorithm SHA256).Hash.ToLowerInvariant();sourceModifiedAt=(Get-Item -LiteralPath $entry).LastWriteTimeUtc.ToString('o');moduleModifiedAt=(Get-Item -LiteralPath $module).LastWriteTimeUtc.ToString('o');listeners=@($rows|ForEach-Object {@{port=[int]$_.LocalPort;address=$_.LocalAddress;pid=[int]$_.OwningProcess}})}|ConvertTo-Json -Depth 6 -Compress`;

export async function probeSupervisorOwner({platform=process.platform,runImpl=run,env=process.env}={}) {
  if(platform!=='win32')return false;
  try {
    // Windows compares environment names case-insensitively. Python launchers
    // uppercase them, and Node can prefer the inherited key over our override.
    const childEnv=Object.fromEntries(Object.entries(env).filter(([key])=>key.toLowerCase()!=='psmodulepath'));
    childEnv.PSModulePath='';
    const result=await runImpl('C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
      ['-NoProfile','-NonInteractive','-Command',SCRIPT],
      {windowsHide:true,timeout:5000,maxBuffer:16384,env:childEnv});
    return isQualifiedSupervisorOwner(JSON.parse(result.stdout.trim()));
  } catch {return false;}
}

// Build a reviewable candidate only. Never edits/starts/stops the live supervisor.
import {readFileSync,writeFileSync,mkdirSync,copyFileSync} from 'node:fs';
import {createHash,randomUUID} from 'node:crypto';
import {join,dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const live='D:/DeepSeekHarness-TestingGrounds/Qwen3.8-Flash Testing/local-models';
const executable='D:/models/nemotron/tools/llama-b11669-cuda12.4/llama-server.exe';
const hash=path=>createHash('sha256').update(readFileSync(path)).digest('hex');
const original=readFileSync(join(live,'local_supervisor.py'),'utf8');
let source=original.replaceAll('\r\n','\n');
function replaceOnce(before,after){if(source.split(before).length!==2)throw Error('Supervisor source changed at a required seam; nothing live was changed.');source=source.replace(before,after);}
replaceOnce('SUP = Supervisor()',`SUP = Supervisor()

# Prepared Mesh protocol: fixed Nemotron lane, original supervisor-owned handles.
from supervisor_mesh_control import MeshControlGate, NemotronSupervisorOwner, MeshSupervisorRoutes
import hashlib as _mesh_hashlib
_MESH_OWNER = NemotronSupervisorOwner(SUP, child_argv(8099, 8199), "${hash(executable)}")
_MESH_ROUTES = MeshSupervisorRoutes(MeshControlGate(_LOCK, _MESH_OWNER.capture, _MESH_OWNER.perform), supervisor_sha256=_mesh_hashlib.sha256(Path(__file__).read_bytes()).hexdigest())`);
const helper=`    def _mesh_control(self):
        if not self.path.startswith("/mesh/v1/"):
            return False
        if self.port != 8099:
            self._json(404, _MESH_ROUTES.envelope({"error": "ROUTE_UNAVAILABLE"}))
            return True
        body = b""
        if self.command == "POST":
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                self._json(415, _MESH_ROUTES.envelope({"error": "JSON_REQUIRED"}))
                return True
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, _MESH_ROUTES.envelope({"error": "INVALID_COMMAND"}))
                return True
            if length <= 0 or length > 4096:
                self._json(413 if length > 4096 else 400, _MESH_ROUTES.envelope({"error": "COMMAND_TOO_LARGE" if length > 4096 else "INVALID_COMMAND"}))
                return True
            old_timeout = self.connection.gettimeout()
            try:
                self.connection.settimeout(3)
                body = self.rfile.read(length)
                if len(body) != length:
                    self._json(400, _MESH_ROUTES.envelope({"error": "INVALID_COMMAND"}))
                    return True
            except (TimeoutError, OSError):
                self._json(408, _MESH_ROUTES.envelope({"error": "COMMAND_READ_TIMEOUT"}))
                return True
            finally:
                self.connection.settimeout(old_timeout)
        code, value = _MESH_ROUTES.handle(self.port, self.command, self.path, body, self.headers.get("Content-Type"))
        self._json(code, value)
        return True

`;
replaceOnce('    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API',helper+'    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API\n        if self._mesh_control():\n            return');
replaceOnce('    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API','    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API\n        if self._mesh_control():\n            return');
const directory=join(root,'data/nemotron-supervisor-candidate',randomUUID());mkdirSync(directory,{recursive:true});
writeFileSync(join(directory,'local_supervisor.py'),source);
copyFileSync(join(root,'lib/supervisor_mesh_control.py'),join(directory,'supervisor_mesh_control.py'));
execFileSync('python',['-c','import ast,sys,pathlib;[ast.parse(pathlib.Path(p).read_text(encoding="utf-8")) for p in sys.argv[1:]]',join(directory,'local_supervisor.py'),join(directory,'supervisor_mesh_control.py')],{windowsHide:true,stdio:'pipe'});
const manifest={schema:'mesh-nemotron-supervisor-candidate/v1',createdAt:new Date().toISOString(),directory,
  qualification:'PREPARED_ONLY_NOT_INSTALLED',modelId:'nemotron-3.5-bolt-74b-a9b',
  liveSource:join(live,'local_supervisor.py'),liveSourceSha256:hash(join(live,'local_supervisor.py')),
  dependencySource:join(live,'launch_local.py'),dependencySha256:hash(join(live,'launch_local.py')),
  executable,executableSha256:hash(executable),
  files:['local_supervisor.py','supervisor_mesh_control.py'].map(path=>({path,sha256:hash(join(directory,path))})),
  remaining:['candidate HTTP fixture','Mesh operation persistence/adapter','reviewed live installation','native load/unload/chat/cancel and restart qualification'],
  changedLiveFiles:false,startedSupervisorOrModelProcesses:false};
writeFileSync(join(directory,'manifest.json'),JSON.stringify(manifest,null,2));
writeFileSync(join(root,'data/nemotron-supervisor-candidate-latest.json'),JSON.stringify(manifest,null,2));
console.log(JSON.stringify({directory,qualification:manifest.qualification,syntax:'PASS',changedLiveFiles:false,startedSupervisorOrModelProcesses:false},null,2));

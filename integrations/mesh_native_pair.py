"""Explicit native writer/gateway lifecycle inside an owned launcher window.

No CLI, implicit retries, credentials, scheduler changes, or automatic cleanup.
The caller keeps this object (and its original handles) across observation waits.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit


class NativePairHold(RuntimeError):
    pass


class MeshNativePair:
    def __init__(self, window, *, service_module, launch_module, roles_module,
                 service_profile, service_sha256, project_approval,
                 mesh_profile, mesh_sha256, reader_approval):
        window.assert_held()
        self.window = window
        expected = window.workspace/'integrations/mind-recovery-candidate'
        for module, name in ((service_module, 'project_service_process_candidate.py'),
                             (launch_module, 'mesh_launch_candidate.py'),
                             (roles_module, 'recall_process_candidate.py')):
            if Path(module.__file__).resolve() != expected/name:
                raise NativePairHold('Participant helper is outside the installed workspace.')
        self.service, self.launch, self.roles = service_module, launch_module, roles_module
        self.service_profile, self.service_sha = Path(service_profile), service_sha256
        self.mesh_profile, self.mesh_sha = Path(mesh_profile), mesh_sha256
        self.project_approval, self.reader_approval = Path(project_approval), Path(reader_approval)
        self.service_settings = self._profile(self.service_profile, self.service_sha)
        self.mesh_settings = self._profile(self.mesh_profile, self.mesh_sha)
        self.writer = self.mesh = self.writer_ticks = self.mesh_ticks = None
        self.stage = 'prepared'
        self._writer_observation = None
        self._stop_requested = False
        self.address = None

    def _profile(self, path, sha):
        body = path.read_bytes()
        if len(body)>65536 or hashlib.sha256(body).hexdigest()!=sha:
            raise NativePairHold('Pinned participant profile changed.')
        return json.loads(body)

    def _require(self, condition, reason):
        self.window.assert_held()
        if not condition:
            self.stage = 'held'
            raise NativePairHold(reason+' Preserve the original handles and attempt; do not retry.')

    def _identity(self, child, ticks):
        self._require(child is not None and ticks is not None
                      and self.roles.creation_ticks(child._handle)==ticks,
                      'Original participant handle identity mismatch.')

    def evidence(self):
        return dict(stage=self.stage, writerPid=self.writer.pid if self.writer else None,
                    writerCreationTicks=self.writer_ticks, meshPid=self.mesh.pid if self.mesh else None,
                    meshCreationTicks=self.mesh_ticks)

    def start_writer(self):
        self._require(self.stage=='prepared' and self.writer is None, 'Writer launch already attempted.')
        self.stage='writer_starting'
        try:
            self.writer,self.writer_ticks=self.service.launch_service(
                self.service_profile,self.service_sha,self.project_approval)
        except Exception as error:
            if getattr(error,'child',None) is not None:
                self.writer=error.child
                self.writer_ticks=self.roles.creation_ticks(self.writer._handle)
            self.stage='held'
            raise NativePairHold('Writer launch not qualified; preserve the same attempt and handles.') from None
        return self.evidence()

    def adopt_started_writer(self, child, ticks):
        """Accept only an original retained handle with exact validated readback."""
        self._require(self.stage=='prepared' and self.writer is None,'Writer already bound.')
        self._identity(child,ticks)
        state=self.service.service_state(self.service_profile,self.service_sha,self.project_approval)
        self._require(child.poll() is None and state['pid']==child.pid
                      and state['creationTicks']==ticks and state['ready'],'Writer readback mismatch.')
        self.writer,self.writer_ticks=child,ticks
        self.stage='writer_ready'
        return self.evidence()

    def observe_writer(self):
        self._require(self.stage in ('writer_starting','writer_ready'),'Writer observation out of order.')
        self._identity(self.writer,self.writer_ticks)
        self._require(self.writer.poll() is None,'Writer exited before qualified gateway startup.')
        path=Path(self.service_settings['readyPath'])
        try:
            raw=path.read_bytes()
            if not raw or len(raw)>65536: return self.evidence()
            json.loads(raw)
        except (FileNotFoundError,json.JSONDecodeError): return self.evidence()
        fingerprint=hashlib.sha256(raw).hexdigest()
        if fingerprint!=self._writer_observation:
            state=self.service.service_state(self.service_profile,self.service_sha,self.project_approval)
            self._require(state['pid']==self.writer.pid and state['creationTicks']==self.writer_ticks,
                          'Writer owner record identifies another process.')
            self._writer_observation=fingerprint
            if state['ready']: self.stage='writer_ready'
            else: self._require(state['state']=='starting','Writer state is not starting or running.')
        return self.evidence()

    def launch_mesh(self):
        self._require(self.stage=='writer_ready' and self.mesh is None,'Gateway launch already attempted or writer not ready.')
        self._identity(self.writer,self.writer_ticks)
        self._require(self.writer.poll() is None,'Writer stopped before gateway launch.')
        self.stage='mesh_starting'
        try:
            self.mesh,self.mesh_ticks,_=self.launch.launch_mesh(self.mesh_profile,self.mesh_sha,self.reader_approval)
        except Exception as error:
            if getattr(error,'child',None) is not None:
                self.mesh=error.child
                self.mesh_ticks=self.roles.creation_ticks(self.mesh._handle)
            self.stage='held'
            raise NativePairHold('Gateway launch not qualified; preserve the same attempt and handles.') from None
        return self.evidence()

    def observe_mesh(self):
        self._require(self.stage in ('mesh_starting','mesh_ready','owner_recorded'),'Gateway observation out of order.')
        self._identity(self.writer,self.writer_ticks);self._identity(self.mesh,self.mesh_ticks)
        self._require(self.writer.poll() is None and self.mesh.poll() is None,'A participant exited before qualification.')
        log=Path(self.mesh_settings['stdoutPath'])
        self._require(log.stat().st_size<=1048576,'Startup output exceeds its bounded observation.')
        for line in log.read_text(encoding='utf-8').splitlines():
            try: row=json.loads(line)
            except ValueError: continue
            if not isinstance(row,dict): continue
            if row.get('event')!='mesh_listening': continue
            self._require(row.get('pid')==self.mesh.pid,'Readiness event identifies another process.')
            def loopback(value, expected_port=None):
                try:
                    self._require(isinstance(value,str),'Missing native readiness address.')
                    address=urlsplit(value)
                    self._require(address.scheme=='http' and address.hostname=='127.0.0.1'
                        and address.port is not None and 1<=address.port<=65535
                        and (expected_port is None or address.port==expected_port)
                        and address.path in ('','/') and not address.query and not address.fragment
                        and not address.username and not address.password,'Unexpected native readiness address.')
                    return address
                except (ValueError,TypeError,AttributeError):
                    self._require(False,'Invalid native readiness address.')
            gateway=loopback(row.get('previewUrl'),int(self.mesh_settings['settings']['MESH_PREVIEW_PORT']))
            backend=loopback(row.get('url'))
            try:
                self.window._owns_gateway(self.mesh.pid,gateway.port)
                self.window._owns_gateway(self.mesh.pid,backend.port)
            except Exception:
                self.stage='held'
                raise NativePairHold('Native listener ownership is not qualified; retain original handles.') from None
            self.address=row['previewUrl']
            if self.stage=='mesh_starting': self.stage='mesh_ready'
            break
        return self.evidence()

    def publish_owner(self, *, previous_sha256, beforeimage_path=None):
        self.observe_mesh()
        self._require(self.stage=='mesh_ready','Gateway owner publication out of order.')
        try:
            record=self.window.publish_native_owner(self.mesh,self.mesh_ticks,self.mesh_profile,self.mesh_sha,
                        previous_sha256=previous_sha256,beforeimage_path=beforeimage_path)
        except Exception:
            self.stage='held'
            raise NativePairHold('Owner publication not qualified; preserve receipt files and original handles.') from None
        self.stage='owner_recorded'
        return record

    def request_stop(self):
        self._require(not self._stop_requested,'Participant stop already requested.')
        self._stop_requested=True
        if self.mesh is not None:
            self._identity(self.mesh,self.mesh_ticks)
            if self.mesh.poll() is None: self.mesh.terminate()
        self.stage='mesh_stopping'
        return self.evidence()

    def observe_stop(self):
        self._require(self._stop_requested and self.stage in ('mesh_stopping','writer_stopping','stopped'),
                      'Participant stop observation out of order.')
        if self.stage=='stopped': return self.evidence()
        if self.mesh is not None:
            self._identity(self.mesh,self.mesh_ticks)
            if self.mesh.poll() is None: return self.evidence()
        if self.writer is None:
            self.stage='stopped';return self.evidence()
        self._identity(self.writer,self.writer_ticks)
        if self.stage=='mesh_stopping':
            if self.writer.poll() is None:
                try:
                    self.service.request_stop(self.service_profile,self.service_sha,self.project_approval)
                except Exception:
                    self.stage='held'
                    raise NativePairHold('Writer stop delivery is uncertain; preserve the same handles and stop record.') from None
            self.stage='writer_stopping'
        if self.writer.poll() is None: return self.evidence()
        self._require(self.writer.returncode==0,'Writer exited without its clean-stop result.')
        state=self.service.service_state(self.service_profile,self.service_sha,self.project_approval)
        self._require(state['state']=='stopped' and not state['processLive']
                      and state['pid']==self.writer.pid and state['creationTicks']==self.writer_ticks,
                      'Writer retirement readback is not exact.')
        self.stage='stopped'
        return self.evidence()

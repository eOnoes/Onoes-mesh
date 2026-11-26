"""Finite scoped native gateway drain/stop/release; no alternate supervisor.

The enclosing owner entry binds the image, native source, exact profile/service
and existing configuration before constructing this object. Imports are inert.
It never loads model credentials, edits gateway configuration or registers a
service. All polls concern one native owner and have explicit deadlines.
"""
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import select
import socket
import stat
import time


class GatewayHeld(RuntimeError):pass


def require(ok):
    if not ok:raise GatewayHeld('Scoped native gateway state is unconfirmed; preserve original evidence')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path,value):
    with path.open('xb') as stream:
        stream.write(json.dumps(value,sort_keys=True,allow_nan=False).encode())
        stream.flush();os.fsync(stream.fileno())


class NativeGateway:
    def __init__(self,*,home,evidence,window_id,plan_sha256,native_source,source_pins,slot_pins,manager,api_port):
        require(os.name=='posix' and type(window_id) is str and 1<=len(window_id)<=80
            and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in window_id)
            and type(api_port) is int and 1024<=api_port<=65535
            and type(plan_sha256) is str and len(plan_sha256)==64 and all(c in '0123456789abcdef' for c in plan_sha256))
        self.home=Path(home);self.evidence=Path(evidence);self.native=Path(native_source)
        require(all(p.is_absolute() and p.resolve(strict=True)==p for p in (self.home,self.evidence,self.native)))
        info=self.evidence.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==os.geteuid() and not stat.S_IMODE(info.st_mode)&0o077
            and self.home.stat().st_uid==os.geteuid() and not self.home.stat().st_mode&0o022)
        self.pins=dict(source_pins);self.slot_pins=dict(slot_pins);self.manager=manager
        self.unit='gateway-default';self.slot=Path(manager.scandir)/self.unit
        require(set(self.slot_pins)=={'run','finish'} and self.slot.is_dir())
        self.slot_identity=(self.slot.stat().st_dev,self.slot.stat().st_ino)
        require({'gateway/status.py','gateway/drain_control.py','hermes_cli/service_manager.py'}<=set(self.pins))
        self._sources()
        from gateway import status,drain_control
        import hermes_cli.service_manager as service_api
        from hermes_cli.service_manager import S6ServiceManager
        require(type(manager) is S6ServiceManager
            and Path(status.__file__).resolve()==self.native/'gateway/status.py'
            and Path(drain_control.__file__).resolve()==self.native/'gateway/drain_control.py'
            and status._get_pid_path()==self.home/'gateway.pid'
            and Path(os.environ.get('HERMES_HOME','/opt/data'))==self.home)
        self.status=status;self.drain=drain_control;self.service_api=service_api;self.api_port=api_port
        self.principal='mesh-cloud-window:'+window_id;self.plan_sha256=plan_sha256
        self.marker=self.drain.drain_request_path(self.home);self.body=None;self.original=None;self.pidfd=None

    def _sources(self):
        require((self.slot.stat().st_dev,self.slot.stat().st_ino)==self.slot_identity)
        for name,pin in self.pins.items():
            p=self.native/name
            require(not Path(name).is_absolute() and '..' not in Path(name).parts
                and p.resolve(strict=True)==p and digest(p)==pin)
        for name,pin in self.slot_pins.items():require(digest(self.slot/name)==pin)

    def _fields(self,*names):
        result=self.manager._svstat_fields(self.unit,*names)
        require(type(result) is list and len(result)==len(names));return result

    def identity(self):
        self._sources();up,pid=self._fields('up','pid')
        require(up in ('true','false'))
        identity=self.status.get_running_pid_identity_strict(self.home/'gateway.pid')
        if up=='false':
            require(int(pid)<=0 and identity is None);return None
        require(identity is not None and type(identity[0]) is int and identity[0]==int(pid)
            and identity[0]>0 and math.isfinite(identity[1]) and identity[1]>0)
        return identity

    def _owned_marker(self):
        require(self.body is not None and self.marker.is_file()
            and self.drain.read_drain_request(home=self.home)==self.body
            and self.body['principal']==self.principal and self.drain.drain_requested(home=self.home))

    def _snapshot(self,identity,*,fresh=True):
        require(self.identity()==identity)
        value=self.status.read_runtime_status(self.home/'gateway_state.json')
        require(type(value) is dict and value.get('pid')==identity[0]
            and self.status.runtime_status_pid_is_live(value)
            and (not fresh or not self.status.runtime_status_is_stale(value,ttl_s=15)))
        return value

    def _drained(self):
        self._owned_marker();value=self._snapshot(self.original,fresh=False)
        if value.get('gateway_state')!='draining' or self.status.runtime_status_is_stale(value,ttl_s=15):return False
        active=value.get('active_agents');work=value.get('active_work')
        # Native _active_work_count sums chat, managed, cron, API and deferred
        # work. The detailed display list is optional/best-effort and can be
        # cleared by native status refreshes; its absence is not a zero count.
        require(type(active) is int and active>=0 and (work is None or type(work) is list))
        observed=datetime.fromisoformat(str(value['updated_at']).replace('Z','+00:00'))
        requested=datetime.fromisoformat(self.body['requested_at'].replace('Z','+00:00'))
        require(observed.tzinfo is not None)
        if observed<requested:return False
        return active==0 and (work is None or work==[])

    def quiesce_and_stop(self,*,seconds=180):
        require(type(seconds) is int and 1<=seconds<=300)
        require(self.original is None and not os.path.lexists(self.marker))
        self.original=self.identity();require(self.original is not None)
        value=self._snapshot(self.original,fresh=False)
        require(value.get('desired_state')=='running')
        require(hasattr(os,'pidfd_open'))
        self.pidfd=os.pidfd_open(self.original[0],0)
        require(self.identity()==self.original)
        write_once(self.evidence/'GATEWAY-STOP-ATTEMPT.json',{'pid':self.original[0],
            'start':self.original[1],'principal':self.principal,'planSha256':self.plan_sha256,'automaticRetry':False})
        self.body=self.drain.write_drain_request(principal=self.principal,suppress_notification=True,home=self.home)
        write_once(self.evidence/'GATEWAY-DRAIN-REQUEST.json',self.body)
        self._owned_marker();deadline=time.monotonic()+seconds
        while not self._drained():
            require(time.monotonic()<deadline);time.sleep(.1)
        write_once(self.evidence/'GATEWAY-DRAINED.json',{'pid':self.original[0],
            'start':self.original[1],'nativeAggregateIdle':True,'nativeMarkerAcknowledged':True})
        self._sources();self.manager.stop(self.unit)
        while True:
            self._owned_marker();up,pid,ready,wanted=self._fields('up','pid','ready','wantedup')
            require(up in ('true','false') and ready in ('true','false') and wanted=='false')
            if up=='false' and pid=='-1':
                poller=select.poll();poller.register(self.pidfd,select.POLLIN)
                events=poller.poll(0)
                require(not any(mask&select.POLLNVAL for _,mask in events))
                retired=any(mask&select.POLLIN for _,mask in events)
                # "ready" is service notification state, not proof of death.
                # The pinned finish scripts only select an exit disposition;
                # they do not own profile/memory writes. Require actual kernel
                # retirement and native wanted-down instead of a readiness bit.
                if retired:break
                if time.monotonic()>=deadline:
                    try:descriptor=os.readlink('/proc/self/fd/'+str(self.pidfd))
                    except OSError:descriptor='unavailable'
                    snapshot=self.status.read_runtime_status(self.home/'gateway_state.json') or {}
                    write_once(self.evidence/'GATEWAY-STOP-HELD.json',{'up':up,'pid':pid,'ready':ready,
                        'wantedup':wanted,'originalPid':self.original[0],'kernelEvents':[m for _,m in events],
                        'descriptor':descriptor,'exitFields':self._fields('exitcode','signum'),
                        'gatewayState':snapshot.get('gateway_state'),'desiredState':snapshot.get('desired_state')})
                    raise GatewayHeld('Original native stop remains held; no replacement started')
                time.sleep(.1);continue
            # The native lock can be released during final clean shutdown.
            # Keep waiting on the retained original kernel identity, not a new
            # interpretation of an advisory PID/lock snapshot.
            require(int(pid)==self.original[0] and time.monotonic()<deadline);time.sleep(.1)
        require(self.status.get_running_pid_identity_strict(self.home/'gateway.pid') is None)
        # Successful s6 stop() is only a request. Its completed native child must
        # exit cleanly, release the profile lock and persist the stopped intent.
        code,signal=self._fields('exitcode','signum')
        # s6-svstat reports -1 for "not killed by a signal", not 0.
        # https://skarnet.org/software/s6/s6-svstat.html
        require(code=='0' and signal=='-1')
        state=self.status.read_runtime_status(self.home/'gateway_state.json')
        require(state and state.get('gateway_state')=='stopped' and state.get('desired_state') in ('running','stopped'))
        # The exiting gateway's last cached status can overwrite the manager's
        # earlier stopped intent. Finalize that same native intent only AFTER
        # the exact process is gone; do not repeat stop or edit JSON directly.
        finalized=state.get('desired_state')!='stopped'
        if finalized:self.service_api._write_gateway_desired_state(self.unit,'stopped')
        state=self.status.read_runtime_status(self.home/'gateway_state.json')
        require(state and state.get('desired_state')=='stopped' and state.get('gateway_state')=='stopped')
        result={'verified':True,'nativeOwnerRetired':True,'nativeAggregateIdle':True,
            'pid':self.original[0],'start':self.original[1],'markerRetained':True,'kernelRetirementConfirmed':True,
            'planSha256':self.plan_sha256,'principal':self.principal,'markerSha256':digest(self.marker),
            'slotIdentity':list(self.slot_identity),'nativeExitCode':code,'nativeSignalNumber':signal,
            'stoppedIntentFinalizedAfterRetirement':finalized}
        write_once(self.evidence/'GATEWAY-STOPPED.json',result);return result

    def assert_stopped(self):
        self._sources();self._owned_marker();require(self.original is not None and self.identity() is None)
        up,pid,wanted=self._fields('up','pid','wantedup')
        require((up,pid,wanted)==('false','-1','false'))
        state=self.status.read_runtime_status(self.home/'gateway_state.json')
        require(state and state.get('desired_state')=='stopped' and state.get('gateway_state')=='stopped')
        return True

    @classmethod
    def resume_stopped(cls,**binding):
        """Reopen a confirmed stop, never repeat a pending stop/start attempt."""
        obj=cls(**binding)
        def read(name):
            p=obj.evidence/name;require(p.resolve(strict=True)==p and p.stat().st_size<=16384)
            return json.loads(p.read_bytes())
        result=read('GATEWAY-STOPPED.json');attempt=read('GATEWAY-STOP-ATTEMPT.json')
        require(result.get('verified') is True and result.get('kernelRetirementConfirmed') is True
            and result['planSha256']==attempt['planSha256']==obj.plan_sha256
            and result['principal']==attempt['principal']==obj.principal
            and result['slotIdentity']==list(obj.slot_identity)
            and (result['pid'],result['start'])==(attempt['pid'],attempt['start'])
            and result['nativeExitCode']=='0' and result['nativeSignalNumber']=='-1'
            and not os.path.lexists(obj.evidence/'GATEWAY-START-ATTEMPT.json'))
        obj.original=(result['pid'],result['start']);obj.body=read('GATEWAY-DRAIN-REQUEST.json')
        require(digest(obj.marker)==result['markerSha256'])
        obj.assert_stopped();return obj

    def release_and_start(self,*,seconds=180):
        """Deliberate release AFTER held client/config qualification, not a test turn."""
        require(type(seconds) is int and 1<=seconds<=300)
        self.assert_stopped()
        require(not os.path.lexists(self.home/'gateway.pid'))
        # Refuse an unidentified port occupant; never use --replace to clear it.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            probe.bind(('127.0.0.1',self.api_port))
        write_once(self.evidence/'GATEWAY-START-ATTEMPT.json',{'service':self.unit,
            'admissionRelease':'normal_native_start','automaticRetry':False})
        self._owned_marker();require(self.drain.clear_drain_request(home=self.home))
        require(not os.path.lexists(self.marker));self._sources();self.manager.start(self.unit)
        deadline=time.monotonic()+seconds
        while True:
            up,pid=self._fields('up','pid');require(up in ('true','false'))
            if up=='true' and int(pid)>0:
                try:
                    current=self.identity();state=self._snapshot(current)
                except (GatewayHeld,RuntimeError):
                    current=state=None
                if state and state.get('gateway_state') in ('running','degraded'):
                    require(current!=self.original and state.get('desired_state')=='running');break
            require(time.monotonic()<deadline);time.sleep(.1)
        result={'verified':True,'sameNativeService':True,'pid':current[0],'start':current[1],
            'admissionRelease':'normal_native_start','modelTest':'NOT_RUN'}
        write_once(self.evidence/'GATEWAY-STARTED.json',result);return result

    def close(self):
        # Handle cleanup never releases admission or changes service intent.
        if self.pidfd is not None:
            os.close(self.pidfd);self.pidfd=None

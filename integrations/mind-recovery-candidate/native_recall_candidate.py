"""Inactive private custody and owned read-only host; no CLI or provisioning.

Call only from a separately reviewed native operator host. Owner authorization,
credential issuance and process enrollment are not supplied by this library.
Current-user DPAPI is not isolation from other same-login/admin processes.
"""
import base64
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

from onoes_mind.enrollment_store import qualify_private_storage
from onoes_mind.recall_binding import RecallBinding, BoundRecallLedger
from onoes_mind.recall_http import RecallServer
from onoes_mind.runtime_keys import _crypt
from checkpoint_candidate import read_plain


SCHEMA='onoes-mind-mesh-recall-credential/v1'
SCOPE='project/onoes-mind/shared'


class NativeRecallError(RuntimeError):
    pass


def require(ok):
    if not ok:raise NativeRecallError('Private Mesh recall custody or binding refused.')


def context(binding):
    require(isinstance(binding,RecallBinding))
    binding=RecallBinding(**asdict(binding))
    require(binding.scope_id==SCOPE)
    raw=json.dumps(dict(purpose=SCHEMA,principal='mesh-recall',binding=asdict(binding)),
                   sort_keys=True,separators=(',',':')).encode('utf-8')
    require(len(raw)<=4096)
    return raw


def token_bytes(token):
    require(type(token) is str and 16<=len(token)<=256
            and all(33<=ord(c)<=126 for c in token))
    return token.encode('ascii')


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result);result[key]=value
    return result


def authorize(binding,token):
    context(binding);token_bytes(token)
    qualify_private_storage(Path(binding.database_path),kind='file')
    reader=BoundRecallLedger(binding.database_path,binding=binding)
    try:require(reader.authenticate(token)=='mesh-recall')
    finally:reader.close()


def load_service_credential(path,*,binding):
    """Return only to trusted native code, never a browser/CLI/logging channel."""
    token=None
    try:
        entropy=context(binding)
        target=qualify_private_storage(Path(path),kind='file')
        envelope=json.loads(read_plain(target,8192),object_pairs_hook=unique)
        require(type(envelope) is dict and set(envelope)=={'schema','protection','bindingSha256','ciphertext'}
                and envelope['schema']==SCHEMA and envelope['protection']=='windows-current-user'
                and envelope['bindingSha256']==hashlib.sha256(entropy).hexdigest())
        require(type(envelope['ciphertext']) is str and len(envelope['ciphertext'])<=4096)
        encrypted=base64.b64decode(envelope['ciphertext'],validate=True)
        # Existing generic DPAPI primitive: UI_FORBIDDEN, never LOCAL_MACHINE.
        # Separate entropy/schema keep this purpose distinct from integrity keys.
        token=_crypt(encrypted,entropy,protect=False).decode('ascii')
        authorize(binding,token)
        return token
    except Exception:
        raise NativeRecallError('Private Mesh recall credential unavailable or binding refused.') from None
    finally:
        token=None  # Reference clearing only, not complete memory erasure.


def seal_service_credential(path,token,*,binding):
    """Protect an already issued purpose-specific token; never issue/reissue one."""
    try:
        entropy=context(binding);raw=token_bytes(token)
        target=Path(path)
        require(target.is_absolute() and '..' not in target.parts and not os.path.lexists(target))
        parent=qualify_private_storage(target.parent)
        require(parent.resolve(strict=True)==parent)
        identity=(parent.stat().st_dev,parent.stat().st_ino)
        authorize(binding,token)
        encrypted=_crypt(raw,entropy,protect=True)
        value=dict(schema=SCHEMA,protection='windows-current-user',
            bindingSha256=hashlib.sha256(entropy).hexdigest(),
            ciphertext=base64.b64encode(encrypted).decode('ascii'))
        data=(json.dumps(value,indent=2)+'\n').encode('utf-8')
        qualify_private_storage(parent)
        require((parent.stat().st_dev,parent.stat().st_ino)==identity)
        with target.open('xb') as output:
            output.write(data);output.flush();os.fsync(output.fileno())
        qualify_private_storage(target,kind='file')
        require(read_plain(target,8192)==data and load_service_credential(target,binding=binding)==token)
        qualify_private_storage(parent)
        require((parent.stat().st_dev,parent.stat().st_ino)==identity)
        return dict(schema=SCHEMA,protected=True,bindingSha256=value['bindingSha256'],
                    fileSha256=hashlib.sha256(data).hexdigest())
    except Exception:
        # Existing/partial files are preserved. Never echo native exceptions.
        raise NativeRecallError('Private Mesh recall credential was not committed successfully; preserve files.') from None


class NativeRecallHost:
    """Only its own read-only ledger/listener; no global process management."""
    def __init__(self,*,binding,credential_path):
        context(binding)
        self.binding=binding;self.credential_path=Path(credential_path)
        self._reader=self._server=None

    def start(self):
        require(self._reader is None and self._server is None)
        reader=server=token=None
        try:
            token=load_service_credential(self.credential_path,binding=self.binding)
            reader=BoundRecallLedger(self.binding.database_path,binding=self.binding)
            require(reader.authenticate(token)=='mesh-recall')
            server=RecallServer(reader);server.start()
            self._reader=reader;self._server=server
            return self.status()
        except Exception:
            if server is not None:
                # Also handle failure between owned socket bind/thread startup.
                thread=getattr(server,'_thread',None)
                if thread is not None and thread.is_alive():server.close()
                elif getattr(server,'_server',None) is not None:server._server.server_close()
            if reader is not None:reader.close()
            raise NativeRecallError('Private read-only Mind host did not start; no automatic retry.') from None
        finally:token=None

    def status(self):
        if self._server is None:return dict(running=False)
        thread=getattr(self._server,'_thread',None)
        if thread is None or not thread.is_alive():return dict(running=False,state='unavailable')
        host,port=self._server.address
        return dict(running=True,pid=os.getpid(),baseUrl=f'http://{host}:{port}/',
                    storeId=self.binding.store_id,environment=self.binding.environment,
                    scopeId=self.binding.scope_id,readOnly=True)

    def native_options(self):
        """Secret-bearing result: direct native constructor input only."""
        require(self.status().get('running') is True)
        return dict(baseUrl=self.status()['baseUrl'],
            token=load_service_credential(self.credential_path,binding=self.binding),
            binding=dict(servicePrincipal='mesh-recall',storeId=self.binding.store_id,
                environment=self.binding.environment,scopeId=self.binding.scope_id,
                reviewRef=self.binding.review_ref))

    def close(self):
        if self._server is not None:self._server.close();self._server=None
        if self._reader is not None:self._reader.close();self._reader=None

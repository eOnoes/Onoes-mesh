"""Encrypted delivery intents, never a local memory/recall authority."""
from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from .config import canonical


class JournalError(RuntimeError):
    pass


class IntentJournal:
    def __init__(self, directory, *, binding, hermes_home, sdk):
        self.root = sdk["enrollment_store"].qualify_private_storage(Path(directory))
        info = self.root.stat()
        self.identity = (info.st_dev,info.st_ino)
        self.agent_id = binding.agent_id
        self._crypt = sdk["runtime_keys"]._crypt
        from dataclasses import asdict
        self.entropy = hashlib.sha256(b"onoes-mind/private-intents/v1\x00" + canonical(
            {"home":str(hermes_home),"binding":asdict(binding)})).digest()

    def _guard(self):
        current = self.root.stat()
        if (self.root.resolve(strict=True) != self.root or (current.st_dev,current.st_ino) != self.identity
                or self.root.is_symlink()):
            raise JournalError("private intent storage changed")

    def _path(self, event_id, *, terminal=False):
        suffix = ".ack.dpapi" if terminal else ".pending.dpapi"
        return self.root/(hashlib.sha256(event_id.encode("utf-8")).hexdigest()+suffix)

    def _sealed(self, raw):
        # The key-envelope primitive deliberately accepts at most 2 KiB. Bind
        # separately protected 1 KiB segments to their position and total count.
        if not 0 < len(raw) <= 65536:raise JournalError("intent exceeds its bound")
        chunks = [raw[i:i+1024] for i in range(0,len(raw),1024)]
        return canonical({"v":1,"chunks":[base64.b64encode(self._crypt(chunk,
            hashlib.sha256(self.entropy+canonical([i,len(chunks)])).digest(),protect=True)).decode("ascii")
            for i,chunk in enumerate(chunks)]})

    def _opened(self, sealed):
        envelope = json.loads(sealed)
        chunks = envelope.get("chunks")
        if (set(envelope) != {"v","chunks"} or envelope["v"] != 1
                or not isinstance(chunks,list) or not 1 <= len(chunks) <= 64):
            raise JournalError("invalid private intent")
        raw = b"".join(self._crypt(base64.b64decode(chunk,validate=True),
            hashlib.sha256(self.entropy+canonical([i,len(chunks)])).digest(),protect=False)
            for i,chunk in enumerate(chunks))
        if len(raw) > 65536:raise JournalError("intent exceeds its bound")
        return raw

    @contextmanager
    def hold(self):
        """Kernel lock, released on process exit; a file's existence is never ownership."""
        self._guard()
        path = self.root/".intent-writer.lock"
        if path.is_symlink():raise JournalError("intent writer is unavailable")
        descriptor = os.open(path,os.O_RDWR|os.O_CREAT|os.O_BINARY|os.O_NOINHERIT,0o600)
        with os.fdopen(descriptor,"r+b") as stream:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"Onoes private intent lock v1\n");stream.flush();os.fsync(stream.fileno())
            stream.seek(0)
            import msvcrt
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise JournalError("another memory write is being reconciled") from None
            try:
                self._guard()
                opened,current = os.fstat(stream.fileno()),path.stat()
                if (opened.st_dev,opened.st_ino) != (current.st_dev,current.st_ino):
                    raise JournalError("intent writer changed")
                yield
            finally:
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

    def _read(self, path):
        self._guard()
        before = path.lstat()
        if path.parent != self.root or not stat.S_ISREG(before.st_mode) or path.is_symlink() or before.st_size > 131072:
            raise JournalError("private intent is unavailable")
        with path.open("rb") as stream:sealed = stream.read(131073)
        try:
            value = json.loads(self._opened(sealed))
            valid = (isinstance(value,dict) and value.get("schema") == "onoes-mind/private-intent/v1"
                     and isinstance(value.get("event_id"),str)
                     and path in (self._path(value["event_id"]),self._path(value["event_id"],terminal=True))
                     and value.get("state") in ("pending","unconfirmed","acknowledged","refused")
                     and isinstance(value.get("request_sha256"),str)
                     and value.get("action") in ("remember","correct","forget"))
            if not valid:raise ValueError()
            if (type(value.get("attempts")) is not int or value["attempts"] < 0
                    or len(value["request_sha256"]) != 64):raise ValueError()
            if value["state"] in ("pending","unconfirmed"):
                payload = value.get("payload")
                if (not isinstance(payload,dict) or payload.get("event_id") != value["event_id"]
                        or hashlib.sha256(canonical({"action":value["action"],"payload":payload})).hexdigest()
                        != value["request_sha256"]):raise ValueError()
            elif "payload" in value:raise ValueError()
            if value["state"] == "acknowledged":
                receipt = value.get("receipt")
                if (not isinstance(receipt,dict) or receipt.get("durable") is not True
                        or receipt.get("agent_id") != self.agent_id
                        or receipt.get("event_id") != value["event_id"]):raise ValueError()
            if path == self._path(value["event_id"],terminal=True) and value["state"] not in ("acknowledged","refused"):
                raise ValueError()
            return value
        except Exception:raise JournalError("private intent could not be verified") from None

    def read(self, event_id):
        for path in (self._path(event_id,terminal=True),self._path(event_id)):
            if path.exists():return self._read(path)
        return None

    def _save(self, value, *, new=False):
        self._guard()
        target = self._path(value["event_id"])
        if target.is_symlink():raise JournalError("private intent target changed")
        sealed = self._sealed(canonical(value))
        if new:
            with target.open("xb") as stream:
                stream.write(sealed);stream.flush();os.fsync(stream.fileno())
        else:
            temporary = self.root/(target.stem+".next-"+uuid.uuid4().hex+".dpapi-work")
            with temporary.open("xb") as stream:
                stream.write(sealed);stream.flush();os.fsync(stream.fileno())
            self._guard()
            os.replace(temporary,target)
        if self._read(target) != value:raise JournalError("private intent did not confirm")
        return value

    def pending(self):
        self._guard()
        paths = list(self.root.glob("*.pending.dpapi"))
        if len(paths) > 128:raise JournalError("private intent journal needs owner maintenance")
        values = [self._read(path) for path in paths]
        return [v for v in values if v["state"] in ("pending","unconfirmed")]

    @staticmethod
    def metadata(value):
        return {key:value[key] for key in ("event_id","action","state","attempts","request_sha256")}

    def prepare(self, action, payload):
        event_id = payload["event_id"]
        digest = hashlib.sha256(canonical({"action":action,"payload":payload})).hexdigest()
        previous = self.read(event_id)
        if previous is not None:
            if previous["request_sha256"] != digest or previous["action"] != action:
                raise JournalError("memory event differs from its saved intent")
            return previous
        outstanding = self.pending()
        if outstanding:raise JournalError("an uncertain memory write needs reconciliation first")
        value = {"schema":"onoes-mind/private-intent/v1","event_id":event_id,"action":action,
                 "request_sha256":digest,"payload":payload,"state":"pending","attempts":0}
        return self._save(value,new=True)

    def attempt(self, value):
        if value["state"] not in ("pending","unconfirmed") or "payload" not in value:
            raise JournalError("only a retained pending intent can be sent")
        return self._save({**value,"attempts":value["attempts"]+1,"state":"pending"})

    def uncertain(self, value):
        return self._save({**value,"state":"unconfirmed"})

    def finish(self, value, *, receipt=None, refused=None):
        terminal = {k:v for k,v in value.items() if k != "payload"}
        terminal["state"] = "acknowledged" if receipt is not None else "refused"
        if receipt is not None:terminal["receipt"] = receipt
        else:terminal["refused_code"] = refused
        result = self._save(terminal)
        self._guard()
        os.replace(self._path(value["event_id"]),self._path(value["event_id"],terminal=True))
        return result

"""Pure, one-shot child admission model; no process or readiness evidence.

One returned token tracks one logical mutation obligation. There is no renewal,
forced release, persistence, timeout, or recovery authority. READY is a trusted
local assertion. STOPPED certifies only closed admission and no live obligations.
Supported admission faults are RuntimeError, ValueError, TypeError and
OverflowError during construction/bookkeeping; they become AdmissionError with
constant diagnostic text and no exception chain. Catastrophic interpreter
failures (including MemoryError and termination) are outside that contract.
"""

from collections import namedtuple
from threading import RLock


STOPPED = "STOPPED"
STARTING = "STARTING"
READY = "READY"
DRAINING = "DRAINING"
STOPPING = "STOPPING"
FAILED = "FAILED"
MAX_ACTIVE = 256
MAX_ADMISSIONS = 4096
_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")
Snapshot = namedtuple("Snapshot", "state generation active total_accepted failure_reason")


class Refusal(ValueError):
    """A rejected call leaves the entire controller unchanged."""


class AdmissionError(RuntimeError):
    """A supported construction/bookkeeping fault was completely rolled back."""


class _Token:
    __slots__ = ()

    def __repr__(self):
        return "<opaque mutation obligation>"

    def __copy__(self):
        raise TypeError("mutation obligations cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("mutation obligations cannot be copied")

    def __reduce__(self):
        raise TypeError("mutation obligations cannot be serialized")

    def __reduce_ex__(self, protocol):
        raise TypeError("mutation obligations cannot be serialized")


def _identifier(value):
    # Reject subclasses before length, iteration, comparison, hashing or repr.
    if type(value) is not str:
        raise Refusal("identifier must be an exact string")
    if not 1 <= len(value) <= 128 or any(c not in _ALPHABET for c in value):
        raise Refusal("invalid identifier")


def _reason(value):
    if type(value) is not str:
        raise Refusal("reason must be an exact string")
    if len(value) > 512 or "\x00" in value:
        raise Refusal("invalid reason")


class Lifecycle:
    """Generation-correlated, lock-linearized, capacity-bounded controller.

    Only the exact retained token object can release its obligation. Aliases
    have bearer authority once; fields, copies and object IDs alone do not.
    This is a cooperative API boundary, not protection against private-memory
    access by arbitrary Python code in the same process.
    """

    def __init__(self):
        self._lock = RLock()
        self._state = STOPPED
        self._generation = None
        self._started = False
        self._failure_reason = None
        self._seen_ids = set()
        self._live = {}
        self._total_accepted = 0

    def _check_generation(self, generation):
        _identifier(generation)
        if generation != self._generation:
            raise Refusal("generation mismatch")

    def start(self, generation):
        with self._lock:
            _identifier(generation)
            if self._started or self._state != STOPPED:
                raise Refusal("controller cannot start")
            self._generation = generation
            self._started = True
            self._state = STARTING

    def mark_ready(self, generation):
        with self._lock:
            self._check_generation(generation)
            if self._state != STARTING:
                raise Refusal("controller cannot become ready")
            self._state = READY

    def begin_drain(self, generation):
        with self._lock:
            self._check_generation(generation)
            if self._state == DRAINING:
                return
            if self._state != READY:
                raise Refusal("controller cannot drain")
            self._state = DRAINING

    def begin_stop(self, generation):
        with self._lock:
            self._check_generation(generation)
            if self._state == STOPPING:
                return
            if self._state not in (STARTING, READY, DRAINING, FAILED):
                raise Refusal("controller cannot stop")
            self._state = STOPPING

    def fail(self, generation, reason):
        with self._lock:
            self._check_generation(generation)
            _reason(reason)
            if self._state == FAILED:
                return
            if self._state not in (STARTING, READY, DRAINING, STOPPING):
                raise Refusal("controller cannot fail")
            if self._failure_reason is None:
                self._failure_reason = reason
            self._state = FAILED

    def admit_mutation(self, generation, operation_id):
        with self._lock:
            self._check_generation(generation)
            _identifier(operation_id)
            if self._state != READY:
                raise Refusal("admission is closed")
            if operation_id in self._seen_ids:
                raise Refusal("operation already admitted")
            if len(self._live) >= MAX_ACTIVE or self._total_accepted >= MAX_ADMISSIONS:
                raise Refusal("admission capacity exhausted")
            token = None
            previous_total = self._total_accepted
            try:
                token = _Token()
                self._seen_ids.add(operation_id)
                self._live[id(token)] = token
                self._total_accepted = previous_total + 1
            except (RuntimeError, ValueError, TypeError, OverflowError):
                self._seen_ids.discard(operation_id)
                if token is not None:
                    self._live.pop(id(token), None)
                self._total_accepted = previous_total
                raise AdmissionError("admission transaction failed") from None
            return token

    def release(self, token):
        with self._lock:
            if self._state not in (READY, DRAINING, STOPPING, FAILED):
                raise Refusal("release is closed")
            if type(token) is not _Token or self._live.get(id(token)) is not token:
                raise Refusal("token is not live")
            del self._live[id(token)]

    def finish_stop(self, generation):
        with self._lock:
            self._check_generation(generation)
            if self._state != STOPPING or self._live:
                raise Refusal("controller cannot finish stop")
            self._state = STOPPED

    def snapshot(self):
        with self._lock:
            return Snapshot(self._state, self._generation, len(self._live),
                            self._total_accepted, self._failure_reason)

"""Explicit stdlib-only Phase B runner: python -I -S -B test_relay_lifecycle.py -v.

Only this file and relay_lifecycle.py are loaded. All source variants are
compiled in memory. No discovery, disk mutants, production hooks or fixtures.
Candidate operations (including setup, snapshots and private evidence reads)
run in bounded daemon probes. A batch probe has one CALL_TIMEOUT for its entire
sequence, so no constituent operation receives a renewed or larger allowance.
The main thread independently enforces each case's setup-plus-oracle deadline.
Timeouts abandon all cases with a data-only fatal marker, without controller
cleanup. The invoking verification wrapper must enforce FULL_RUN_TIMEOUT.
"""

import ast
import copy
import json
import pickle
from pathlib import Path
import sys
import threading
import time
import types
import unittest


SYNC_WAIT = 0.25
CALL_TIMEOUT = 0.50
JOIN_TIMEOUT = 0.25
CASE_TIMEOUT = 1.50
MUTANT_TIMEOUT = 1.50
FATAL_EXIT = 0.25
FULL_RUN_TIMEOUT = 30.0
GEN = "generation:1"
WRONG = "generation:2"
SOURCE = Path(__file__).with_name("relay_lifecycle.py").read_text(encoding="utf-8")
TEST_SOURCE = Path(__file__).read_text(encoding="utf-8")


class HarnessError(Exception):
    """Setup, instrumentation or unexpected exceptions never count as kills."""


class SemanticViolation(AssertionError):
    """A specific contract oracle, distinguishable from an unrelated error."""


class FatalTimeout(BaseException):
    def __init__(self, label, deadline):
        self.label = label
        self.deadline = deadline


def require(condition, label):
    if not condition:
        raise SemanticViolation(label)


def await_completion(event, deadline):
    # Every event wait is at most SYNC_WAIT; the absolute deadline never renews.
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if event.wait(min(SYNC_WAIT, remaining)):
            return True


class Probe:
    def __init__(self, function, label):
        self.label = label
        self.started = time.monotonic()
        self.done = threading.Event()
        self.outcome = None

        def work():
            try:
                self.outcome = (True, function())
            except BaseException as error:
                self.outcome = (False, error)
            self.finished = time.monotonic()
            self.done.set()

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def collect(self):
        if not await_completion(self.done, self.started + CALL_TIMEOUT):
            raise FatalTimeout(self.label, CALL_TIMEOUT)
        self.worker.join(JOIN_TIMEOUT)
        if self.worker.is_alive():
            raise FatalTimeout(self.label + ":join", JOIN_TIMEOUT)
        good, value = self.outcome
        if not good:
            raise value
        return value


def bounded(function, label="candidate-call"):
    return Probe(function, label).collect()


def load(source=SOURCE, extra=None):
    module = types.ModuleType("phase_b_candidate")
    if extra:
        module.__dict__.update(extra)
    exec(compile(source, "<phase-b-in-memory>", "exec"), module.__dict__)
    return module


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise HarnessError("source variant anchor is not unique")
    return source.replace(old, new, 1)


def refused(module, function):
    try:
        function()
    except module.Refusal:
        return True
    return False


def evidence(controller):
    # This private inspection is only for isolated candidates, under their lock.
    with controller._lock:
        return (controller.snapshot(), frozenset(controller._seen_ids),
                tuple(controller._live.items()), controller._total_accepted,
                controller._started)


def digest(controller):
    with controller._lock:
        snap = controller.snapshot()
        return (snap.state, snap.active, len(controller._live),
                snap.total_accepted, len(controller._seen_ids))


def fresh(module, state="READY"):
    controller = module.Lifecycle()
    if state == "INITIAL":
        return controller
    controller.start(GEN)
    if state != "STARTING":
        controller.mark_ready(GEN)
    if state == "DRAINING":
        controller.begin_drain(GEN)
    elif state == "STOPPING":
        controller.begin_stop(GEN)
    elif state == "FAILED":
        controller.fail(GEN, "first")
    elif state == "TERMINAL":
        controller.begin_stop(GEN)
        controller.finish_stop(GEN)
    return controller


class LifecycleTests(unittest.TestCase):
    def __init__(self, methodName, module):
        super().__init__(methodName)
        self.module = module

    def test_admission_rejected_in_every_non_ready_state(self):
        def check():
            m = self.module
            for state in ("INITIAL", "STARTING", "DRAINING", "STOPPING", "FAILED", "TERMINAL"):
                c = fresh(m, state)
                before = evidence(c)
                outcome = refused(m, lambda: c.admit_mutation(GEN, "operation"))
                require(outcome and evidence(c) == before, "M01:non-ready admission")
        bounded(check)

    def test_every_control_rejects_stale_generation(self):
        def check():
            m = self.module
            for state in ("STARTING", "READY", "DRAINING", "STOPPING", "FAILED", "TERMINAL"):
                c = fresh(m, state)
                controls = (lambda: c.start(WRONG), lambda: c.mark_ready(WRONG),
                            lambda: c.begin_drain(WRONG), lambda: c.begin_stop(WRONG),
                            lambda: c.fail(WRONG, "later"),
                            lambda: c.admit_mutation(WRONG, "operation"),
                            lambda: c.finish_stop(WRONG))
                for control in controls:
                    before = evidence(c)
                    outcome = refused(m, control)
                    require(outcome and evidence(c) == before, "M03:stale generation")
        bounded(check)

    def test_release_requires_exact_object_identity(self):
        def check():
            m = self.module
            c = fresh(m)
            token = c.admit_mutation(GEN, "operation")
            # Empty-slot clones have precisely the same public fields as token.
            fake = m._Token()
            reconstructed = object.__new__(type(token))
            other = fresh(m)
            foreign = other.admit_mutation(GEN, "operation")
            for forged in (fake, reconstructed, foreign, object(), None, "operation", id(token)):
                before = evidence(c)
                outcome = refused(m, lambda: c.release(forged))
                require(outcome and evidence(c) == before, "M04:token identity")
            previous = m.Lifecycle()
            previous.start(WRONG)
            previous.mark_ready(WRONG)
            stale = previous.admit_mutation(WRONG, "operation")
            previous.begin_stop(WRONG)
            previous.release(stale)
            previous.finish_stop(WRONG)
            before = evidence(c)
            require(refused(m, lambda: c.release(stale)) and evidence(c) == before,
                    "M04:token identity")
            for attempt in (lambda: copy.copy(token), lambda: copy.deepcopy(token),
                            lambda: pickle.dumps(token), lambda: json.dumps(token),
                            lambda: token.__reduce__(), lambda: token.__reduce_ex__(4)):
                try:
                    attempt()
                except TypeError:
                    pass
                else:
                    raise SemanticViolation("M04:token serialization")
            require(repr(token) == "<opaque mutation obligation>", "opaque repr")
            alias = token
            c.release(alias)
            require(c.snapshot().active == 0, "genuine alias")
            other.release(foreign)
            require(refused(m, lambda: other.release(token)), "cross-controller stale token")
        bounded(check)

    def test_duplicate_release_is_noop_or_refusal(self):
        def check():
            m = self.module
            c = fresh(m)
            token = c.admit_mutation(GEN, "operation")
            c.release(token)
            before = evidence(c)
            outcome = refused(m, lambda: c.release(token))
            require(outcome and evidence(c) == before, "M05:duplicate release")
            c.begin_stop(GEN)
            c.finish_stop(GEN)
            before = evidence(c)
            require(refused(m, lambda: c.release(token)) and evidence(c) == before,
                    "M05:duplicate release")
        bounded(check)

    def test_failure_retains_authentic_obligation(self):
        def check():
            m = self.module
            c = fresh(m)
            token = c.admit_mutation(GEN, "operation")
            c.fail(GEN, "")
            require(digest(c) == (m.FAILED, 1, 1, 1, 1), "M06:failure retains token")
            c.fail(GEN, "ignored")
            c.begin_stop(GEN)
            c.fail(GEN, "ignored again")
            require(c.snapshot().failure_reason == "", "first empty reason")
            c.begin_stop(GEN)
            require(not refused(m, lambda: c.release(token)), "M06:failure retains token")
            c.finish_stop(GEN)
            require(digest(c) == (m.STOPPED, 0, 0, 1, 1), "failure closure")
            require(refused(m, lambda: c.start(GEN)), "one-shot failed closure")
        bounded(check)

    def test_finish_stop_refuses_with_live_token(self):
        def check():
            m = self.module
            c = fresh(m)
            token = c.admit_mutation(GEN, "operation")
            c.begin_stop(GEN)
            before = evidence(c)
            outcome = refused(m, lambda: c.finish_stop(GEN))
            require(outcome and evidence(c) == before, "M07:outstanding work")
            c.release(token)
            c.finish_stop(GEN)
            require(digest(c) == (m.STOPPED, 0, 0, 1, 1), "closure after release")
        bounded(check)

    def rollback(self, mutant_id):
        def check():
            m = self.module
            c = fresh(m)
            existing = c.admit_mutation(GEN, "existing") if not hasattr(m, "_fault") else None
            # Fault controls start empty, with the injected boundary armed once.
            before = evidence(c)
            try:
                token = c.admit_mutation(GEN, "retry-id")
            except m.AdmissionError as error:
                require(str(error) == "admission transaction failed" and
                        error.__cause__ is None and error.__suppress_context__,
                        mutant_id + ":bounded exception")
            else:
                if hasattr(m, "_fault"):
                    raise HarnessError("injected fault was not reached")
                c.release(token)
                return  # Uninstrumented baseline has no fault to simulate.
            require(evidence(c) == before, mutant_id + ":rollback")
            token = c.admit_mutation(GEN, "retry-id")
            require(c.snapshot().total_accepted == len(c._seen_ids), mutant_id + ":rollback")
            c.release(token)
            if existing is not None:
                c.release(existing)
        bounded(check, mutant_id)

    def test_admission_rollback_token_construction(self):
        self.rollback("M08")

    def test_admission_rollback_seen_id_insert(self):
        self.rollback("M09")

    def test_admission_rollback_live_insert(self):
        self.rollback("M10")

    def test_admission_rollback_total_update(self):
        self.rollback("M11")

    def test_mutant_split_commit_drain_window(self):
        m = self.module
        c = bounded(lambda: fresh(m))
        if not hasattr(m, "checked"):
            bounded(lambda: c.begin_drain(GEN))
            before = bounded(lambda: evidence(c))
            outcome = bounded(lambda: refused(m, lambda: c.admit_mutation(GEN, "operation")))
            require(outcome and bounded(lambda: evidence(c)) == before, "M02:post-drain commit")
            return
        probe = Probe(lambda: c.admit_mutation(GEN, "operation"), "M02 admission")
        if not m.checked.wait(SYNC_WAIT):
            raise FatalTimeout("M02 missing worker-produced checked acknowledgment", SYNC_WAIT)
        bounded(lambda: c.begin_drain(GEN), "M02 drain")
        before = bounded(lambda: evidence(c), "M02 drained evidence")
        require(before[0].state == m.DRAINING and before[0].active == 0,
                "M02 setup drain state")
        m.commit_gate.set()
        try:
            probe.collect()
        except m.Refusal:
            rejected = True
        else:
            rejected = False
        after = bounded(lambda: evidence(c), "M02 committed evidence")
        require(rejected and after == before, "M02:post-drain commit")

    def test_complete_transition_matrix(self):
        def check():
            m = self.module
            rows = {
                "INITIAL": {"start": m.STARTING},
                "STARTING": {"mark_ready": m.READY, "begin_stop": m.STOPPING, "fail": m.FAILED},
                "READY": {"begin_drain": m.DRAINING, "begin_stop": m.STOPPING,
                          "fail": m.FAILED, "admit_mutation": m.READY},
                "DRAINING": {"begin_drain": m.DRAINING, "begin_stop": m.STOPPING, "fail": m.FAILED},
                "STOPPING": {"begin_stop": m.STOPPING, "fail": m.FAILED, "finish_stop": m.STOPPED},
                "FAILED": {"begin_stop": m.STOPPING, "fail": m.FAILED},
                "TERMINAL": {},
            }
            for state, allowed in rows.items():
                for method in ("start", "mark_ready", "begin_drain", "begin_stop", "fail",
                               "admit_mutation", "finish_stop"):
                    c = fresh(m, state)
                    before = evidence(c)
                    args = (GEN, "literal") if method in ("fail", "admit_mutation") else (GEN,)
                    try:
                        result = getattr(c, method)(*args)
                    except m.Refusal:
                        require(method not in allowed and evidence(c) == before,
                                "transition refusal matrix")
                    else:
                        require(method in allowed and c.snapshot().state == allowed[method],
                                "transition success matrix")
                        if (state, method) in (("DRAINING", "begin_drain"),
                                               ("STOPPING", "begin_stop"), ("FAILED", "fail")):
                            require(evidence(c) == before, "exact same-state no-op")
                        if method == "admit_mutation":
                            c.release(result)
            # Every accepted token remains valid through each admission-closed state.
            for state in (m.READY, m.DRAINING, m.STOPPING, m.FAILED):
                c = fresh(m)
                token = c.admit_mutation(GEN, "operation")
                if state == m.DRAINING:
                    c.begin_drain(GEN)
                elif state == m.STOPPING:
                    c.begin_stop(GEN)
                elif state == m.FAILED:
                    c.fail(GEN, "first")
                c.release(token)
                require(c.snapshot().active == 0, "release state matrix")
            c = fresh(m)
            c.begin_stop(GEN)
            c.finish_stop(GEN)
            require(refused(m, lambda: c.start(WRONG)), "one-shot normal closure")
        bounded(check)

    def test_supported_fault_types_preserve_existing_obligations(self):
        def check():
            for error_type in (RuntimeError, ValueError, TypeError, OverflowError):
                # This additional fault follows the total assignment, proving
                # restoration even after every bookkeeping field changed.
                source = replace_once(SOURCE, "                self._total_accepted = previous_total + 1",
                                      "                self._total_accepted = previous_total + 1\n                _fault()")
                calls = []

                def fault():
                    calls.append(True)
                    if len(calls) == 2:
                        raise error_type("diagnostic must not escape")

                m = load(source, {"_fault": fault})
                c = fresh(m)
                existing = c.admit_mutation(GEN, "existing")
                before = evidence(c)
                try:
                    c.admit_mutation(GEN, "retry")
                except m.AdmissionError as error:
                    require(str(error) == "admission transaction failed", "bounded fault types")
                else:
                    raise HarnessError("supported fault was not exercised")
                require(evidence(c) == before, "existing obligation and total rollback")
                retry = c.admit_mutation(GEN, "retry")
                c.release(retry)
                c.release(existing)
                c.begin_stop(GEN)
                c.finish_stop(GEN)
                require(digest(c) == (m.STOPPED, 0, 0, 2, 2), "post-fault genuine closure")
        bounded(check, "supported-fault batch")

    def test_refusals_do_not_construct_tokens(self):
        def check():
            created = []
            source = replace_once(SOURCE, "                token = _Token()",
                                  "                _created.append(True)\n                token = _Token()")
            m = load(source, {"_created": created})
            for state in ("INITIAL", "STARTING", "DRAINING", "STOPPING", "FAILED", "TERMINAL"):
                c = fresh(m, state)
                require(refused(m, lambda: c.admit_mutation(GEN, "operation")), "closed admission")
            require(not created, "no token construction outside READY")
            c = fresh(m)
            for call in (lambda: c.admit_mutation(WRONG, "operation"),
                         lambda: c.admit_mutation(GEN, "bad/id")):
                require(refused(m, call), "invalid admission")
            require(not created, "validation before token construction")
            token = c.admit_mutation(GEN, "same")
            c.release(token)
            require(refused(m, lambda: c.admit_mutation(GEN, "same")) and len(created) == 1,
                    "duplicate before token construction")
            for i in range(m.MAX_ACTIVE):
                c.admit_mutation(GEN, "bounded:" + str(i))
            require(refused(m, lambda: c.admit_mutation(GEN, "capacity")) and
                    len(created) == 1 + m.MAX_ACTIVE, "capacity before token construction")
        bounded(check, "construction-order batch")

    def test_exact_input_and_hostile_objects(self):
        def check():
            m = self.module
            touched = []

            class Hostile:
                def attack(self, *args):
                    touched.append(True)
                    raise AssertionError("caller code invoked")
                __eq__ = __hash__ = __str__ = __repr__ = attack

            class HostileString(str):
                __eq__ = __hash__ = __str__ = __repr__ = Hostile.attack
                __len__ = __iter__ = __contains__ = Hostile.attack

            invalid = (None, True, 1, b"id", [], {}, Hostile(), HostileString("valid"),
                       "", "x" * 129, " ", "a b", "a/b", "a\\b", "é", "a\x00", "\n", "a+", "a@")
            for value in invalid:
                c = m.Lifecycle()
                before = evidence(c)
                require(refused(m, lambda: c.start(value)) and evidence(c) == before,
                        "invalid initial generation")
                c = fresh(m)
                before = evidence(c)
                for call in (lambda: c.start(value), lambda: c.mark_ready(value),
                             lambda: c.begin_drain(value), lambda: c.begin_stop(value),
                             lambda: c.fail(value, "reason"), lambda: c.finish_stop(value),
                             lambda: c.admit_mutation(value, "operation"),
                             lambda: c.admit_mutation(GEN, value)):
                    require(refused(m, call) and evidence(c) == before, "invalid identifier atomicity")
            for value in (None, 1, b"reason", Hostile(), HostileString("reason"), "x" * 513, "a\x00"):
                for state in ("READY", "FAILED"):
                    c = fresh(m, state)
                    before = evidence(c)
                    require(refused(m, lambda: c.fail(GEN, value)) and evidence(c) == before,
                            "invalid repeated reason")
            c = fresh(m)
            token = c.admit_mutation(GEN, "operation")
            before = evidence(c)
            require(refused(m, lambda: c.release(Hostile())) and evidence(c) == before,
                    "hostile release")
            c.release(token)
            require(not touched, "no hostile methods")
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for identifier in ("a", "a" * 128, alphabet):
                c = m.Lifecycle()
                c.start(identifier)
                c.mark_ready(identifier)
                c.release(c.admit_mutation(identifier, identifier))
            for reason in ("", "λ" * 512, " \ntext:🦊"):
                c = fresh(m)
                c.fail(GEN, reason)
                require(c.snapshot().failure_reason == reason, "literal reason boundary")
        bounded(check)

    def test_capacity_and_permanent_id_retention(self):
        def check():
            m = self.module
            require(m.MAX_ACTIVE == 256 and m.MAX_ADMISSIONS == 4096, "fixed capacities")
            c = fresh(m)
            tokens = [c.admit_mutation(GEN, "op:" + str(i)) for i in range(m.MAX_ACTIVE)]
            before = evidence(c)
            require(refused(m, lambda: c.admit_mutation(GEN, "retry-capacity")) and
                    evidence(c) == before, "active capacity atomicity")
            c.release(tokens.pop())
            tokens.append(c.admit_mutation(GEN, "retry-capacity"))
            c.begin_drain(GEN)
            c.fail(GEN, "at capacity")
            c.begin_stop(GEN)
            for token in tokens:
                c.release(token)
            c.finish_stop(GEN)
            require(c.snapshot().active == 0, "cleanup at active capacity")
            c = fresh(m)
            for i in range(m.MAX_ADMISSIONS):
                token = c.admit_mutation(GEN, "id:" + str(i))
                c.release(token)
            before = evidence(c)
            for operation_id in ("overflow", "id:0"):
                require(refused(m, lambda: c.admit_mutation(GEN, operation_id)) and
                        evidence(c) == before, "admissions capacity and retained ids")
            require(digest(c) == (m.READY, 0, 0, 4096, 4096), "total capacity invariant")
            c.begin_drain(GEN)
            c.fail(GEN, "full")
            c.begin_stop(GEN)
            c.finish_stop(GEN)
            # Duplicate IDs refuse even when capacity is not exhausted.
            c = fresh(m)
            c.release(c.admit_mutation(GEN, "same"))
            before = evidence(c)
            require(refused(m, lambda: c.admit_mutation(GEN, "same")) and evidence(c) == before,
                    "id retained after release")
        bounded(check, "capacity batch")

    def test_detached_immutable_snapshot(self):
        def check():
            m = self.module
            c = fresh(m)
            initial = c.snapshot()
            token = c.admit_mutation(GEN, "operation")
            current = c.snapshot()
            require(initial == m.Snapshot(m.READY, GEN, 0, 0, None), "detached snapshot")
            require(current == m.Snapshot(m.READY, GEN, 1, 1, None), "coherent snapshot")
            for value in current:
                require(type(value) in (str, int, type(None)), "data-only snapshot")
            try:
                current.active = 99
            except AttributeError:
                pass
            else:
                raise SemanticViolation("immutable snapshot")
            require(refused(m, lambda: c.release(current)), "snapshot has no authority")
            c.release(token)
            require(current.active == 1, "snapshot not live view")
        bounded(check)

    def history_pair(self, name, state, operations, expected, overlap=False):
        m = self.module
        c, token = bounded(lambda: self.history_setup(state))
        records = []
        record_lock = threading.Lock()
        barrier = threading.Barrier(2) if overlap else None

        def operation(index):
            if barrier is not None:
                try:
                    barrier.wait(SYNC_WAIT)
                except threading.BrokenBarrierError:
                    raise FatalTimeout(name + ":barrier", SYNC_WAIT) from None
            invoked = time.monotonic()
            method = operations[index]
            try:
                if method == "admit":
                    result = c.admit_mutation(GEN, "history-id")
                    outcome = "accepted"
                elif method == "release":
                    result = c.release(token)
                    outcome = "accepted"
                elif method == "fail":
                    result = c.fail(GEN, "history")
                    outcome = "accepted"
                elif method == "ready":
                    result = c.mark_ready(GEN)
                    outcome = "accepted"
                elif method == "stop":
                    result = c.begin_stop(GEN)
                    outcome = "accepted"
                elif method == "finish":
                    result = c.finish_stop(GEN)
                    outcome = "accepted"
                elif method == "drain":
                    result = c.begin_drain(GEN)
                    outcome = "accepted"
                elif method == "snapshot":
                    result = c.snapshot()
                    outcome = "accepted"
                else:
                    raise HarnessError("unknown history operation")
            except m.Refusal:
                result, outcome = None, "refused"
            completed = time.monotonic()
            with record_lock:
                records.append((index, method, invoked, completed, outcome, result))

        first = Probe(lambda: operation(0), name + ":first")
        if overlap:
            second = Probe(lambda: operation(1), name + ":second")
            first.collect()
            second.collect()
        else:
            first.collect()
            second = Probe(lambda: operation(1), name + ":second")
            second.collect()
        final = bounded(lambda: digest(c))
        ordered = sorted(records)
        outcomes = tuple(row[4] for row in ordered)
        require((outcomes, final) in expected, name + ":serial oracle")
        if not overlap:
            require(ordered[0][3] <= ordered[1][2], name + ":completed-call precedence")
        if "snapshot" in operations:
            snap = ordered[operations.index("snapshot")][5]
            require(snap in (m.Snapshot(m.READY, GEN, 0, 0, None),
                             m.Snapshot(m.DRAINING, GEN, 0, 0, None)),
                    name + ":legal snapshot")
        # Data-only evidence: no live token/result reference is printed.
        print("HISTORY " + json.dumps({"name": name, "overlap": overlap,
              "calls": [{"index": r[0], "method": r[1], "invoked": r[2],
                         "completed": r[3], "outcome": r[4]} for r in ordered],
              "state_active_registry_total_seen": final}), flush=True)

    def history_setup(self, state):
        c = fresh(self.module, "STARTING" if state == "STARTING" else "READY")
        token = None
        if state in ("LIVE", "STOPPING_LIVE"):
            token = c.admit_mutation(GEN, "initial-id")
        if state == "STOPPING_LIVE":
            c.begin_stop(GEN)
        return c, token

    def test_history_duplicate_id_contenders(self):
        accepted = (("accepted", "refused"), ("READY", 1, 1, 1, 1))
        refused_first = (("refused", "accepted"), ("READY", 1, 1, 1, 1))
        self.history_pair("duplicate-id", "READY", ("admit", "admit"), (accepted,))
        self.history_pair("duplicate-id", "READY", ("admit", "admit"),
                          (accepted, refused_first), overlap=True)

    def test_history_two_releases(self):
        a = (("accepted", "refused"), ("READY", 0, 0, 1, 1))
        b = (("refused", "accepted"), ("READY", 0, 0, 1, 1))
        self.history_pair("two-releases", "LIVE", ("release", "release"), (a,))
        self.history_pair("two-releases", "LIVE", ("release", "release"), (a, b), overlap=True)

    def test_history_release_finish_stop(self):
        a = (("accepted", "accepted"), ("STOPPED", 0, 0, 1, 1))
        b = (("refused", "accepted"), ("STOPPING", 0, 0, 1, 1))
        self.history_pair("release-before-finish", "STOPPING_LIVE", ("release", "finish"), (a,))
        self.history_pair("finish-before-release", "STOPPING_LIVE", ("finish", "release"), (b,))
        self.history_pair("release-finish-overlap", "STOPPING_LIVE", ("release", "finish"),
                          (a, (("accepted", "refused"), ("STOPPING", 0, 0, 1, 1))), overlap=True)

    def test_history_fail_admit(self):
        a = (("accepted", "refused"), ("FAILED", 0, 0, 0, 0))
        b = (("accepted", "accepted"), ("FAILED", 1, 1, 1, 1))
        self.history_pair("fail-before-admit", "READY", ("fail", "admit"), (a,))
        self.history_pair("admit-before-fail", "READY", ("admit", "fail"), (b,))
        self.history_pair("fail-admit-overlap", "READY", ("fail", "admit"), (a, b), overlap=True)

    def test_history_ready_stop(self):
        a = (("accepted", "accepted"), ("STOPPING", 0, 0, 0, 0))
        b = (("accepted", "refused"), ("STOPPING", 0, 0, 0, 0))
        self.history_pair("ready-before-stop", "STARTING", ("ready", "stop"), (a,))
        self.history_pair("stop-before-ready", "STARTING", ("stop", "ready"), (b,))
        self.history_pair("ready-stop-overlap", "STARTING", ("ready", "stop"),
                          (a, (("refused", "accepted"), ("STOPPING", 0, 0, 0, 0))), overlap=True)

    def test_history_snapshot_transition(self):
        expected = ((("accepted", "accepted"), ("DRAINING", 0, 0, 0, 0)),)
        self.history_pair("snapshot-before-drain", "READY", ("snapshot", "drain"), expected)
        self.history_pair("drain-before-snapshot", "READY", ("drain", "snapshot"), expected)
        self.history_pair("snapshot-drain-overlap", "READY", ("snapshot", "drain"),
                          expected, overlap=True)

    def test_history_admission_drain(self):
        a = (("accepted", "accepted"), ("DRAINING", 1, 1, 1, 1))
        b = (("accepted", "refused"), ("DRAINING", 0, 0, 0, 0))
        self.history_pair("admission-before-drain", "READY", ("admit", "drain"), (a,))
        self.history_pair("drain-before-admission", "READY", ("drain", "admit"), (b,))
        self.history_pair("admission-drain-overlap", "READY", ("admit", "drain"),
                          (a, (("refused", "accepted"), ("DRAINING", 0, 0, 0, 0))), overlap=True)

    def test_source_and_import_boundary(self):
        production = ast.parse(SOURCE)
        imports = {n.module if isinstance(n, ast.ImportFrom) else a.name
                   for n in ast.walk(production) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names}
        require(imports == {"collections", "threading"}, "production import allowlist")
        calls = {n.func.id for n in ast.walk(production)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        require(not calls.intersection({"open", "exec", "eval", "compile", "__import__"}),
                "production side-effect source inspection")
        attrs = {n.attr for n in ast.walk(production) if isinstance(n, ast.Attribute)}
        require(not attrs.intersection({"Thread", "Timer", "start", "environ", "getenv",
                                        "socket", "Popen", "write", "read_text"}),
                "production no background or persistence")
        test_imports = {n.module if isinstance(n, ast.ImportFrom) else a.name
                        for n in ast.walk(ast.parse(TEST_SOURCE))
                        if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        require(test_imports == {"ast", "copy", "json", "pickle", "pathlib", "sys",
                                 "threading", "time", "types", "unittest"}, "test import allowlist")
        # Every dependency comes from the isolated interpreter's stdlib; the only
        # non-stdlib source is explicitly compiled above, never imported by path.
        require(not {"relay_supervisor", "server", "relay_chat", "relay_runner",
                     "test_relay_supervisor", "test_relay_turn_meta"}.intersection(sys.modules),
                "no production or Phase A imports")
        require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
                "required isolated interpreter flags")


KILLERS = (
    ("M01", "test_admission_rejected_in_every_non_ready_state", "M01:non-ready admission"),
    ("M02", "test_mutant_split_commit_drain_window", "M02:post-drain commit"),
    ("M03", "test_every_control_rejects_stale_generation", "M03:stale generation"),
    ("M04", "test_release_requires_exact_object_identity", "M04:token identity"),
    ("M05", "test_duplicate_release_is_noop_or_refusal", "M05:duplicate release"),
    ("M06", "test_failure_retains_authentic_obligation", "M06:failure retains token"),
    ("M07", "test_finish_stop_refuses_with_live_token", "M07:outstanding work"),
    ("M08", "test_admission_rollback_token_construction", "M08:rollback"),
    ("M09", "test_admission_rollback_seen_id_insert", "M09:rollback"),
    ("M10", "test_admission_rollback_live_insert", "M10:rollback"),
    ("M11", "test_admission_rollback_total_update", "M11:rollback"),
)


def variant(mutant_id, defective):
    source = SOURCE
    extra = {}
    if mutant_id == "M01" and defective:
        source = replace_once(source, '            if self._state != READY:\n                raise Refusal("admission is closed")',
                              '            if False:\n                raise Refusal("admission is closed")')
    elif mutant_id == "M02":
        old = '''        with self._lock:
            self._check_generation(generation)
            _identifier(operation_id)
            if self._state != READY:
                raise Refusal("admission is closed")'''
        new = old + '''
        checked.set()
        if not commit_gate.wait(SYNC_WAIT):
            raise FatalTimeout("M02 commit gate deadline", SYNC_WAIT)
        with self._lock:'''
        if not defective:
            new += '''
            if self._state != READY:
                raise Refusal("admission is closed")'''
        source = replace_once(source, old, new)
        extra = {"checked": threading.Event(), "commit_gate": threading.Event(),
                 "SYNC_WAIT": SYNC_WAIT, "FatalTimeout": FatalTimeout}
    elif mutant_id == "M03" and defective:
        source = replace_once(source, "        if generation != self._generation:", "        if False:")
    elif mutant_id == "M04" and defective:
        source = replace_once(source, '''            if type(token) is not _Token or self._live.get(id(token)) is not token:
                raise Refusal("token is not live")
            del self._live[id(token)]''', '''            if type(token) is not _Token or not self._live:
                raise Refusal("token is not live")
            self._live.pop(next(iter(self._live)))''')
    elif mutant_id == "M05" and defective:
        source = replace_once(source, "        self._total_accepted = 0",
                              "        self._total_accepted = 0\n        self._duplicate_releases = 0")
        source = replace_once(source, '''            if type(token) is not _Token or self._live.get(id(token)) is not token:
                raise Refusal("token is not live")''', '''            if type(token) is not _Token or self._live.get(id(token)) is not token:
                self._duplicate_releases += 1
                return''')
        source = replace_once(source, "return Snapshot(self._state, self._generation, len(self._live),",
                              "return Snapshot(self._state, self._generation, len(self._live) - self._duplicate_releases,")
    elif mutant_id == "M06" and defective:
        source = replace_once(source, "            self._state = FAILED", "            self._live.clear()\n            self._state = FAILED")
    elif mutant_id == "M07" and defective:
        source = replace_once(source, "            if self._state != STOPPING or self._live:",
                              "            if self._state != STOPPING:")
    elif mutant_id in ("M08", "M09", "M10", "M11"):
        points = {
            "M08": "                token = _Token()",
            "M09": "                self._seen_ids.add(operation_id)",
            # M10's fault is at live insertion, after seen, before registry commit.
            "M10": "                self._live[id(token)] = token",
            "M11": "                self._total_accepted = previous_total + 1",
        }
        line = points[mutant_id]
        injected = "                _fault(self, token, operation_id)"
        source = replace_once(source, line, line + "\n" + injected if mutant_id in ("M08", "M09")
                              else injected + "\n" + line)
        hits = []

        def fault(controller, token, operation_id):
            if hits:
                return
            if type(token).__name__ != "_Token":
                raise HarnessError("fault boundary lacks provisional token")
            seen = operation_id in controller._seen_ids
            live = controller._live.get(id(token)) is token
            if (seen, live) != {"M08": (False, False), "M09": (True, False),
                                "M10": (True, False), "M11": (True, True)}[mutant_id]:
                raise HarnessError("fault did not occur at the specified partial boundary")
            hits.append(mutant_id)
            raise RuntimeError("bounded supported injection")

        extra = {"_fault": fault, "_fault_hits": hits}
        if defective:
            if mutant_id == "M08":
                source = replace_once(source, '                raise AdmissionError("admission transaction failed") from None',
                                      '                self._live[id(token)] = token\n                raise AdmissionError("admission transaction failed") from None')
            else:
                source = replace_once(source, '''                self._seen_ids.discard(operation_id)
                if token is not None:
                    self._live.pop(id(token), None)
                self._total_accepted = previous_total''', "                pass")
    return load(source, extra)


# Explicit inventory: no unittest discovery or implicit imports.
TEST_NAMES = tuple(row[1] for row in KILLERS) + (
    "test_complete_transition_matrix",
    "test_exact_input_and_hostile_objects",
    "test_supported_fault_types_preserve_existing_obligations",
    "test_refusals_do_not_construct_tokens",
    "test_capacity_and_permanent_id_retention",
    "test_detached_immutable_snapshot",
    "test_history_duplicate_id_contenders",
    "test_history_two_releases",
    "test_history_release_finish_stop",
    "test_history_fail_admit",
    "test_history_ready_stop",
    "test_history_snapshot_transition",
    "test_history_admission_drain",
    "test_source_and_import_boundary",
)


def run_case(label, function, timeout):
    # Independent observer: case workers cannot extend the outer deadline by
    # renewing a per-call wait or becoming wedged during setup/oracle execution.
    done = threading.Event()
    outcome = []
    started = time.monotonic()

    def work():
        try:
            function()
        except BaseException as error:
            outcome.append(error)
        done.set()

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    if not await_completion(done, started + timeout):
        raise FatalTimeout(label, timeout)
    if outcome:
        raise outcome[0]
    worker.join(min(JOIN_TIMEOUT, max(0, timeout - (time.monotonic() - started))))
    if worker.is_alive():
        raise FatalTimeout(label + ":join", JOIN_TIMEOUT)


def main():
    verbose = sys.argv[1:] == ["-v"]
    if sys.argv[1:] not in ([], ["-v"]):
        print("FAIL unsupported focused-runner arguments", flush=True)
        return 1
    count, kills = 0, []
    label = "load"
    started = time.monotonic()
    try:
        module = load()
        for name in TEST_NAMES:
            label = "baseline:" + name
            case = LifecycleTests(name, module)
            run_case(label, getattr(case, name), CASE_TIMEOUT)
            count += 1
            if verbose:
                print("PASS " + label, flush=True)
        for mutant_id, name, oracle in KILLERS:
            label = mutant_id + ":corrected:" + name

            def corrected():
                candidate = variant(mutant_id, False)
                case = LifecycleTests(name, candidate)
                getattr(case, name)()
                if hasattr(candidate, "_fault_hits") and candidate._fault_hits != [mutant_id]:
                    raise HarnessError("corrected fault control not exercised exactly once")

            run_case(label, corrected, MUTANT_TIMEOUT)
            count += 1
            if verbose:
                print("PASS " + label, flush=True)
            label = mutant_id + ":mutant:" + name

            def kill():
                candidate = variant(mutant_id, True)
                case = LifecycleTests(name, candidate)
                try:
                    getattr(case, name)()
                except SemanticViolation as error:
                    if str(error) != oracle:
                        raise HarnessError("mutant failed an unrelated oracle") from None
                    if hasattr(candidate, "_fault_hits") and candidate._fault_hits != [mutant_id]:
                        raise HarnessError("mutant fault boundary not exercised exactly once")
                else:
                    raise HarnessError("mutation survivor: " + mutant_id)

            run_case(label, kill, MUTANT_TIMEOUT)
            count += 1
            kills.append(mutant_id)
            print("KILL " + mutant_id + " " + name + " oracle=" + oracle, flush=True)
    except FatalTimeout as error:
        detected = time.monotonic()
        print("FATAL_TIMEOUT " + json.dumps({"case": label, "probe": error.label,
              "deadline_seconds": error.deadline, "fatal_exit_seconds": FATAL_EXIT,
              "detected_monotonic": detected}), flush=True)
        return 1  # No joins, snapshots, finalizers or further cases after timeout.
    except BaseException as error:
        print("FAIL " + json.dumps({"case": label, "error_type": type(error).__name__,
              "detail": str(error)}), flush=True)
        return 1  # Skips, setup errors, unrelated exceptions and survivors fail.
    print("RESULT " + json.dumps({"tests": count, "baseline_tests": len(TEST_NAMES),
          "corrected_controls": len(KILLERS), "mutants_killed": kills, "skips": 0,
          "failures": 0, "survivors": 0, "hangs": 0,
          "elapsed_seconds": time.monotonic() - started,
          "bytecode_disabled": sys.dont_write_bytecode}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

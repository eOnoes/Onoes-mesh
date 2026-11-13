# Relay native-result evidence candidate

Purpose: distinguish a native answer mismatch from a Relay display mismatch for
an already saved, exact native run. This is a sanitized adapter candidate, not
an installed change or proof that either layer caused the observed mismatch.

Base: `D:/Dev/Onoes-Relay/relay_native_receipts.py`, SHA256
`ad0444ac043dcdb5aa6baa008c4b58b47144f56925b39759a44dbbeafac2fafd`.
Preserve and compare that base before applying; never overwrite shared changes.
The complete changed helper is supplied for review. The original uses Windows
line endings; preserve the saved base and compare source content before rollout.

The existing receipt reader uses its existing authenticated native client and
saved send/run binding. The candidate adds `resultEvidence` only after native
identity/status validation. A terminal text result from the exact saved
conversation yields its exact UTF-8 SHA256 and character/byte counts. Wrong
conversation, nonterminal, nontext, invalid UTF-8 or over-1-MiB results return an
unavailable reason. No text, credentials, arbitrary requested run, new task,
retry, conversation mutation, or worker-retirement conclusion is added.

Run from the Mesh checkout:

```powershell
python -m unittest test.relay_native_result_test -v
```

These synthetic acceptance tests exercise the candidate receipt reader with a
client exposing only `run_status`; it cannot dispatch. They do not prove the
live mismatch's origin. Mesh's previously verified 577 tests remain separate.

Next integration step: review this candidate against the actual loaded Relay
helper, preserve its base, deploy through the established Relay maintenance
path, then GET the existing review's receipt without resending. Compare its
digest with the already captured displayed reply using exact UTF-8 bytes.
Equal hashes show identical native/displayed text. Different hashes establish
a difference but need stream evidence before blaming display. Unavailable
evidence keeps the cause unknown. Never accept a review solely from a digest.

The direct unauthenticated native GET returned 401 and was not retried with
guessed credentials or bypassed. The reviewed one-file candidate was subsequently
installed through Relay's exact owned-process maintenance path while idle, with
the old helper backed up. Only Relay restarted. The existing authenticated
receipt path then returned a digest identical to the captured displayed answer.
That excludes display substitution for this exact result; the native run already
returned the older answer. Input/admission/execution correlation remains unknown.
Private rollout/result evidence stays outside this sanitized packet. No native
gateway restart, message resend or review acceptance occurred.

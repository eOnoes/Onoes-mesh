"""Pinned current native lookup candidate; no installer or activation."""
import ast
import hashlib


def local_receipt_candidate(native_root, *, baselines):
    path='gateway/session_controls.py';raw=(native_root/path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=baselines[path]:
        raise RuntimeError('Native local receipt source changed')
    original=raw.decode('utf-8').replace('\r\n','\n');candidate=original
    before="'prompt.submit', 'prompt.receipt',"
    if candidate.count(before)!=1:raise RuntimeError('Unexpected implicit profile receipt list')
    candidate=candidate.replace(before,"'prompt.submit', 'prompt.receipt', 'prompt.lookup',")
    before="'prompt.receipt': self.receipt"
    if candidate.count(before)!=1:raise RuntimeError('Unexpected native receipt handler registry')
    candidate=candidate.replace(before,before+", 'prompt.lookup': self.lookup")
    tree=ast.parse(candidate);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AuthorityConnection')
    fn=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='receipt')
    method="""
    async def lookup(self, ref, params):
        if (set(params) - {'session_id', 'submission_id', 'include_result'}
                or not isinstance(params.get('submission_id'), str)
                or not params['submission_id'] or len(params['submission_id']) > 256):
            raise RuntimeStoreError('invalid_params')
        self.authority.authorize(self.actor, ref, 'session:read')
        from hermes_state_runtime import find_session_admission
        saved = await asyncio.to_thread(find_session_admission, self.authority.db,
            principal_id=self.actor.subject, session_id=ref.session_id, request_id=params['submission_id'])
        out = {'found': saved is not None, 'session_id': ref.session_id, 'submission_id': params['submission_id']}
        if saved is not None:
            out['receipt'] = await self.receipt(ref, {'admission_id': saved['admission_id'],
                'include_result': params.get('include_result') is True})
        return out

"""
    lines=candidate.splitlines(True);lines.insert(fn.end_lineno,method);candidate=''.join(lines);ast.parse(candidate)
    contract_path='tui_gateway/contracts/canonical.py';raw_contract=(native_root/contract_path).read_bytes()
    if hashlib.sha256(raw_contract).hexdigest()!=baselines[contract_path]:
        raise RuntimeError('Native canonical receipt contract changed')
    contract_original=raw_contract.decode('utf-8').replace('\r\n','\n');lines=contract_original.splitlines(True)
    next_class=next(n for n in ast.parse(contract_original).body if isinstance(n,ast.ClassDef) and n.name=='PromptCancelParams')
    declaration="""class PromptLookupParams(Params):
    session_id: str
    submission_id: str
    include_result: bool | None = None


class PromptLookupResult(Result):
    found: bool
    session_id: str
    submission_id: str
    receipt: PromptReceiptResult | None = None


canonical_method("prompt.lookup", params=PromptLookupParams, result=PromptLookupResult,
                 doc="Read-only exact submission lookup within the caller principal and session.")


"""
    lines.insert(next_class.lineno-1,declaration);contract=''.join(lines);ast.parse(contract)
    return {path:original,contract_path:contract_original},{path:candidate,contract_path:contract}



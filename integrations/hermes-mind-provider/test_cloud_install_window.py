"""Failure containment in the finite window; not deployed adapter acceptance."""
import json

import pytest

from cloud_install_window import CloudWindowHeld,install_once


SECRET='synthetic-sensitive-value-must-not-reach-receipts'


class Adapter:
    def __init__(self,fail=None,uncertain_hold=False):
        self.fail=fail;self.uncertain_hold=uncertain_hold;self.calls=[]
        self.admitted=True;self.gateway=True;self.windows=True;self.config='original'
        self.new_access=False;self.records=['original-record'];self.qualified=False
        self.public_code=False;self.client_credentials=False

    def preflight(self,pin,evidence):
        self.calls.append('preflight');return True

    def __getattr__(self,name):
        def operation():
            self.calls.append(name)
            if name=='quiesce_gateway':self.admitted=False;self.gateway=False
            elif name=='retire_windows':
                assert not self.gateway and not self.admitted;self.windows=False
            elif name=='materialize_client':
                assert not self.windows and not self.gateway;self.public_code=True
            elif name=='capture_curated':
                assert self.public_code and not self.gateway and not self.new_access
            elif name=='admit_cyony':
                assert not self.windows and not self.gateway
                self.new_access=True;self.records.append('curated-record')
            elif name=='backup_after':assert not self.windows and not self.gateway
            elif name=='start_windows':self.windows=True
            elif name=='deliver_client':
                assert self.public_code and self.new_access and self.windows and not self.gateway
                self.client_credentials=True
            elif name=='select_configuration':
                assert self.client_credentials;self.config='new'
            elif name=='qualify_held':
                assert self.windows and not self.gateway and not self.admitted
                assert self.config=='new' and self.new_access;self.qualified=True
            elif name=='release_gateway':
                assert self.qualified;self.admitted=True;self.gateway=True
            elif name=='hold_for_rollback':
                if self.uncertain_hold:raise RuntimeError(SECRET)
                self.admitted=False;self.gateway=False;self.windows=False
            elif name=='revoke_new_access':
                assert not self.windows and not self.gateway;self.new_access=False
            elif name=='restore_configuration':self.config='original'
            elif name=='restore_windows':
                assert self.config=='original' and not self.new_access;self.windows=True
            elif name=='qualify_original_held':
                assert not self.gateway and not self.admitted
                assert self.windows and self.config=='original' and not self.new_access
            elif name=='release_original_gateway':self.admitted=True;self.gateway=True
            if name==self.fail:raise RuntimeError(SECRET)
            return {'verified':True,'privateResult':SECRET}
        return operation


def receipts(root):return b''.join(p.read_bytes() for p in root.iterdir())


def test_success_qualifies_before_release_and_never_copies_private_hook_results(tmp_path):
    a=Adapter();result=install_once(a,tmp_path,'a'*64)
    assert result['installed'] and a.new_access and a.gateway and a.admitted
    assert a.calls.index('qualify_held')<a.calls.index('release_gateway')
    assert a.calls.index('materialize_client')<a.calls.index('capture_curated')<a.calls.index('admit_cyony')<a.calls.index('deliver_client')
    assert a.records==['original-record','curated-record']
    assert SECRET.encode() not in receipts(tmp_path)
    assert json.loads((tmp_path/'COMPLETE.json').read_bytes())['realModelAcceptance']=='NOT_RUN'


@pytest.mark.parametrize('failure',['quiesce_gateway','backup_before','materialize_client','capture_curated',
    'admit_cyony','backup_after','deliver_client','qualify_held','release_gateway','qualify_running'])
def test_failure_reholds_before_revocation_and_preserves_canonical_records(tmp_path,failure):
    a=Adapter(failure);result=install_once(a,tmp_path,'b'*64)
    assert result['restored'] and not result['installed']
    assert a.gateway and a.admitted and a.windows and a.config=='original' and not a.new_access
    assert a.calls.index('hold_for_rollback')<a.calls.index('revoke_new_access')
    assert a.calls.index('qualify_original_held')<a.calls.index('release_original_gateway')
    assert 'original-record' in a.records
    if 'admit_cyony' in a.calls:assert 'curated-record' in a.records
    assert SECRET.encode() not in receipts(tmp_path)
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()};calls=list(a.calls)
    with pytest.raises(CloudWindowHeld):install_once(a,tmp_path,'b'*64)
    assert a.calls==calls and before=={p.name:p.read_bytes() for p in tmp_path.iterdir()}


def test_uncertain_actor_retirement_prohibits_revoke_restore_and_false_success(tmp_path):
    a=Adapter('qualify_running',uncertain_hold=True)
    with pytest.raises(CloudWindowHeld):install_once(a,tmp_path,'c'*64)
    assert a.new_access and a.config=='new'
    assert 'revoke_new_access' not in a.calls and 'restore_configuration' not in a.calls
    assert (tmp_path/'ROLLBACK-HELD.json').exists()
    assert not (tmp_path/'COMPLETE.json').exists() and not (tmp_path/'RESTORED.json').exists()
    assert SECRET.encode() not in receipts(tmp_path)


def test_denied_or_failed_preflight_changes_nothing_and_redacts_error(tmp_path):
    a=Adapter();a.preflight=lambda *_:False
    with pytest.raises(CloudWindowHeld):install_once(a,tmp_path,'d'*64)
    assert not list(tmp_path.iterdir()) and a.calls==[] and not a.new_access
    def rejected(*_):raise ValueError(SECRET)
    a.preflight=rejected
    with pytest.raises(CloudWindowHeld) as error:install_once(a,tmp_path,'d'*64)
    assert SECRET not in str(error.value) and not list(tmp_path.iterdir())

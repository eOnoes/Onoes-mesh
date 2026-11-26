"""Real Windows replacement and partial-selection recovery on owned files only."""
import importlib.util
import os
from pathlib import Path
import sys

import pytest

MIND=Path(os.environ['MIND_SOURCE'])
PROVIDER=Path(os.environ['MESH_PROVIDER_SOURCE'])
sys.path[:0]=[str(MIND),str(Path(os.environ['MIND_TEST_SOURCE'])/'tests'),str(PROVIDER)]
from test_cloud_curated_transfer import private_dir
from cloud_source_selection import prepare,install,restore,sha,SelectionHeld

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Actual Windows ReplaceFileW')


@pytest.fixture
def owned(tmp_path):
    workspace=tmp_path/'copied-mesh';native=workspace/'integrations/mind-recovery-candidate'
    native.mkdir(parents=True)
    replacements={}
    for name in ('project_service_process_candidate.py','native_project_sync_candidate.py'):
        path=native/name;before=b'# synthetic original\n';after=b'# synthetic selected\n'
        path.write_bytes(before)
        replacements[str(path)]={'beforeSha256':sha(before),'afterSha256':sha(after),'after':after}
    wrapper=tmp_path/'mesh-capture-first-hidden.vbs'
    old,new=tmp_path/'old-startup.json',tmp_path/'new-startup.json'
    text='Run --approval '+str(old)+' --sha256 '+'a'*64+'\n'
    wrapper.write_bytes(text.encode())
    evidence=private_dir(tmp_path/'private-evidence')
    entry=PROVIDER.parent.parent/'data/deep-enrollment-candidate-20261125/operations/deep-configuration-switch.py'
    spec=importlib.util.spec_from_file_location('unchanged_native_configuration_primitive',entry)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    kwargs=dict(workspace=workspace,wrapper=wrapper,replacements=replacements,
        original_startup=old,new_startup=new,original_sha256='a'*64,new_sha256='b'*64,
        expected_wrapper_sha256=sha(wrapper.read_bytes()))
    return kwargs,evidence,module.atomic_replace


@pytest.mark.parametrize('encoding',['utf-8','utf-16','utf-16-be'])
def test_native_select_restore_preserves_every_original_byte_and_wrapper_encoding(owned,encoding):
    kwargs,evidence,atomic=owned
    wrapper=kwargs['wrapper'];text=wrapper.read_text()
    wrapper.write_bytes((b'\xfe\xff' if encoding=='utf-16-be' else b'')+text.encode(encoding))
    kwargs['expected_wrapper_sha256']=sha(wrapper.read_bytes())
    changes=prepare(**kwargs)
    result=install(changes,evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:True)
    assert result['filesSelected']==3 and result['existingTaskUnchanged']
    assert all(p.read_bytes()==after for p,_,after in changes)
    assert str(kwargs['new_startup']) in wrapper.read_bytes().decode(encoding)
    result=restore(evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:True)
    assert result['filesRestored']==3 and all(p.read_bytes()==before for p,before,_ in changes)


def test_partial_selection_restores_only_known_changed_file(owned):
    kwargs,evidence,atomic=owned;changes=prepare(**kwargs);calls=[]
    def fail_second(*args):
        calls.append(args[0])
        if len(calls)==2:raise RuntimeError('Synthetic bounded pre-replacement fault')
        return atomic(*args)
    with pytest.raises(RuntimeError):install(changes,evidence=evidence,atomic_replace=fail_second,assert_quiescent=lambda:True)
    assert (evidence/'SOURCE-SELECTION-ATTEMPT.json').exists()
    assert all((evidence/('source-before-'+str(i)+'.bytes')).read_bytes()==before for i,(_,before,_) in enumerate(changes))
    assert restore(evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:True)['filesRestored']==1
    assert all(p.read_bytes()==before for p,before,_ in changes)


def test_foreign_drift_blocks_all_restoration(owned):
    kwargs,evidence,atomic=owned;changes=prepare(**kwargs)
    install(changes,evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:True)
    changes[-1][0].write_bytes(b'foreign edit')
    before={p:p.read_bytes() for p,_,_ in changes}
    with pytest.raises(SelectionHeld):restore(evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:True)
    assert all(p.read_bytes()==raw for p,raw in before.items())


def test_admission_required_and_original_attempt_cannot_repeat(owned):
    kwargs,evidence,atomic=owned;changes=prepare(**kwargs)
    with pytest.raises(SelectionHeld):install(changes,evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:False)
    assert not list(evidence.iterdir())
    install(changes,evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:True)
    with pytest.raises(SelectionHeld):install(changes,evidence=evidence,atomic_replace=atomic,assert_quiescent=lambda:True)
    assert all(p.read_bytes()==after for p,_,after in changes)


def test_unrelated_source_is_refused(owned):
    kwargs,evidence,atomic=owned
    kwargs['replacements'][str(kwargs['workspace']/'unrelated.py')]={'beforeSha256':'a'*64,'afterSha256':'b'*64,'after':b'x'}
    with pytest.raises(SelectionHeld):prepare(**kwargs)
    assert not list(evidence.iterdir())

"""Deployed public Echo/Deep client code against the candidate private HTTP host."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

MIND=Path(os.environ['MIND_SOURCE']).resolve();sys.path.insert(0,str(MIND))
from onoes_mind import Ledger
from onoes_mind.agent_home import AgentHome,AgentHomeBinding,enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient,AgentHomeServer,home_binding_sha256
from onoes_mind.recall_binding import RecallBinding,prepare_store_identity


@pytest.fixture
def current_host(tmp_path):
    database=tmp_path/'synthetic.sqlite'
    writer=Ledger(database,environment_id='synthetic-legacy-client',audit_key=b'a'*32,deletion_key=b'b'*32)
    writer.create_principal('operator');writer.issue_credential('operator','synthetic-owner')
    store_id=prepare_store_identity(writer,environment='synthetic-legacy-client',authority_ref='fixture:owner')
    stat=database.stat()
    store=RecallBinding(str(database),store_id,'synthetic-legacy-client','fixture:owner',
        'project/onoes-mind/shared',stat.st_dev,stat.st_ino,'fixture:custody','fixture:withdraw','fixture:review')
    homes=[];tokens={}
    for actor in ('echo','deep'):
        binding=AgentHomeBinding(store,actor)
        enroll_agent_home(writer,binding,operator_token='synthetic-owner',
            save_new_token=lambda token,actor=actor:tokens.setdefault(actor,token) is not None)
        homes.append(AgentHome(writer,binding))
    host=AgentHomeServer(homes);host.start()
    try:yield host,store,tokens
    finally:host.close();writer.close()


WORKER=r'''
import json,sys
from pathlib import Path
request=json.load(sys.stdin);sys.path.insert(0,request['source'])
import onoes_mind
assert Path(onoes_mind.__file__).resolve().parent==Path(request['source'])/'onoes_mind'
from onoes_mind.agent_home import AgentHomeBinding
from onoes_mind.agent_home_http import AgentHomeClient,AgentHomeTransportError,home_binding_sha256
from onoes_mind.recall_binding import RecallBinding
actor=request['actor'];binding=AgentHomeBinding(RecallBinding(**request['store']),actor)
assert home_binding_sha256(binding)==request['bindingSha256']
client=AgentHomeClient(request['endpoint'],agent_id=actor,binding_sha256=request['bindingSha256'],
    credential_provider=lambda:request['token'],timeout=5)
saved=client.call('remember',{'event_id':'legacy-save-'+actor,'text':'Legacyharbor old selected preference'})
row,=client.call('recall',{'query':'legacyharbor'})['records']
assert row['record_id']==saved['record_id']
client.call('correct',{'event_id':'legacy-correct-'+actor,'record_id':row['record_id'],
    'expected_revision_id':row['revision_id'],'text':'Legacyharbor current selected preference'})
current=client.call('recall',{'query':'legacyharbor'})
row,=current['records'];assert row['claim']=='Legacyharbor current selected preference'
assert current['agent_id']==actor and current['scope_id']=='agent/'+actor+'/private'
wrong=AgentHomeClient(request['endpoint'],agent_id=actor,binding_sha256=request['bindingSha256'],
    credential_provider=lambda:request['otherToken'],timeout=5)
try:wrong.call('recall',{'query':'legacyharbor'})
except AgentHomeTransportError:pass
else:raise AssertionError('Another actor credential must be refused')
client.call('forget',{'event_id':'legacy-forget-'+actor,'record_id':row['record_id'],
    'expected_revision_id':row['revision_id']})
assert client.call('recall',{'query':'legacyharbor'})['records']==[]
print(json.dumps({'actor':actor,'oldBindingMatches':True,'privateSaveRecallCorrectionForget':True,'crossActorCredentialDenied':True}))
'''


@pytest.mark.parametrize('actor,variable',[('echo','MIND_LEGACY_ECHO_SOURCE'),('deep','MIND_LEGACY_DEEP_SOURCE')])
def test_actual_deployed_client_still_uses_its_private_contract(current_host,actor,variable):
    source=os.environ.get(variable)
    if not source:pytest.skip('Explicit public deployed client source is required')
    host,store,tokens=current_host;other='deep' if actor=='echo' else 'echo'
    binding=host.homes[actor].binding
    request=dict(source=source,actor=actor,store=asdict(store),endpoint=host.base_url,
        bindingSha256=home_binding_sha256(binding),token=tokens[actor],otherToken=tokens[other])
    result=subprocess.run([sys.executable,'-I','-B','-c',WORKER],input=json.dumps(request),
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    reply=json.loads(result.stdout);assert reply['actor']==actor and reply['crossActorCredentialDenied']
    peer=AgentHomeClient(host.base_url,agent_id=other,binding_sha256=home_binding_sha256(host.homes[other].binding),
        credential_provider=lambda:tokens[other],timeout=5)
    assert peer.call('recall',{'query':'legacyharbor'})['records']==[]

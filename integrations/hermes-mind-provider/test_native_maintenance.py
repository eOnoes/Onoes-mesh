"""Native drain-file/API refusal with a disposable owner configuration switch."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import weakref

import pytest

from test_native_shared_reader import staged_native_reader,profile,shared,tls_home,context_store,scope
from portable_owner_switch import SwitchError,prepare_switch,install_switch,rollback_switch

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Native POSIX drain/config rehearsal')


def test_native_external_drain_holds_api_admission_through_config_switch_and_rollback(staged_native_reader,monkeypatch):
    from gateway import drain_control
    import gateway.run as runtime
    from gateway.platforms.api_server import APIServerAdapter

    f=staged_native_reader;home=f['profile']['home']
    runner=object.__new__(runtime.GatewayRunner)
    runner._running=True;runner._draining=False;runner._external_drain_active=False
    busy=[True];states=[];observed=[]
    # No gateway/model is started: only the native watcher and native API refusal run.
    # These synthetic work hooks do not prove real deployed worker quiescence.
    runner._active_work_count=lambda:int(busy[0])
    runner._update_runtime_status=states.append
    runner._persist_active_agents=lambda:observed.append(int(busy[0]))
    runner._serving_state=lambda:'running'
    monkeypatch.setattr(runtime,'_gateway_runner_ref',weakref.ref(runner))
    adapter=object.__new__(APIServerAdapter)

    async def wait_for(predicate):
        async with asyncio.timeout(3):
            while not predicate():await asyncio.sleep(.01)

    def idle():
        return (drain_control.drain_requested(home=home)
                and runner._external_drain_active and not busy[0])

    async def exercise():
        assert not drain_control.drain_request_path(home).exists()
        assert adapter._draining_response() is None
        drain_control.write_drain_request(principal='synthetic-owner',home=home)
        watcher=asyncio.create_task(runner._drain_control_watcher(interval=.01))
        try:
            await wait_for(lambda:runner._external_drain_active)
            response=adapter._draining_response()
            assert response.status==503 and response.headers['Retry-After']=='1'
            assert 'gateway_draining' in response.text
            assert busy[0] and observed and observed[0]==1
            plan=prepare_switch(**f['arguments'])
            with pytest.raises(SwitchError):
                install_switch(plan,backup_directory=f['backup'],assert_quiescent=idle)
            assert (home/'config.yaml').read_bytes()==f['original']
            assert not list(f['backup'].iterdir())
            busy[0]=False
            receipt=install_switch(plan,backup_directory=f['backup'],assert_quiescent=idle)
            assert adapter._draining_response().status==503
            assert rollback_switch(plan,receipt,assert_quiescent=idle)['restored']
            assert adapter._draining_response().status==503
            assert drain_control.clear_drain_request(home=home)
            await wait_for(lambda:not runner._external_drain_active)
            assert adapter._draining_response() is None
            assert states[0]=='draining' and states[-1]=='running'
        finally:
            runner._running=False
            watcher.cancel()
            await asyncio.gather(watcher,return_exceptions=True)
            drain_control.clear_drain_request(home=home)
    with scope(home):asyncio.run(exercise())
    for name,raw in f['native_files'].items():assert (home/name).read_bytes()==raw


@pytest.mark.parametrize('case,active',[('old-epoch',False),('expired',False),('malformed',True)])
def test_native_marker_epoch_expiry_and_corruption_define_hold_lifetime(tmp_path,monkeypatch,case,active):
    from gateway import drain_control
    monkeypatch.setattr(drain_control,'current_instantiation_epoch',lambda:'synthetic-current-epoch')
    home=tmp_path/'synthetic-home';home.mkdir(mode=0o700)
    body=drain_control.write_drain_request(principal='synthetic-owner',home=home)
    path=drain_control.drain_request_path(home)
    assert drain_control.drain_requested(home=home)
    if case=='old-epoch':body['epoch']='synthetic-previous-epoch'
    elif case=='expired':body['requested_at']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    path.write_text('{' if case=='malformed' else json.dumps(body),encoding='utf-8')
    assert drain_control.drain_requested(home=home) is active
    assert path.exists()  # Observation never silently deletes another owner's marker.
    assert drain_control.clear_drain_request(home=home)
    assert not drain_control.drain_requested(home=home)

import test from 'node:test';
import assert from 'node:assert/strict';
import {tailscaleAccess} from '../lib/tailscale-access.mjs';
const policy={login:'owner@example.test',host:'machine.example.ts.net:8453'};
const request={socket:{remoteAddress:'127.0.0.1'},headers:{host:policy.host,'tailscale-user-login':policy.login}};
test('Tailscale owner identity is accepted only at the configured private host',()=>{
  assert.equal(tailscaleAccess(request,policy),true);
  assert.equal(tailscaleAccess(request,{}),false);
  assert.equal(tailscaleAccess({...request,headers:{host:policy.host}},policy),false);
  assert.equal(tailscaleAccess({...request,headers:{...request.headers,'tailscale-user-login':'someone-else@example.test'}},policy),false);
  assert.equal(tailscaleAccess({...request,headers:{...request.headers,host:'other.example.ts.net:8453'}},policy),false);
  assert.equal(tailscaleAccess({...request,socket:{remoteAddress:'192.168.1.20'}},policy),false);
});

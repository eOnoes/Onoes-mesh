import test from 'node:test';
import assert from 'node:assert/strict';
import {mockUI,response,flush,bodyFor} from './app-ui-fixture.mjs';

const token='r'.repeat(43),csrf='s'.repeat(43);
for(const skew of [-90000,0,90000])test(`recovery accepts a server-issued challenge with phone clock offset ${skew}ms`,async()=>{
 const serverNow=Date.now();class PhoneDate extends Date {static now(){return serverNow+skew;}}
 const ui=mockUI({DateImpl:PhoneDate,responder:route=>{
  if(route==='/api/trial-session/bootstrap')return response(403,{});
  if(route==='/api/trial-session/recovery-challenge')return response(200,{challenge:token,expiresAt:serverNow+30000});
  if(route==='/api/trial-session/recovery-complete')return response(201,{csrfToken:csrf,expiresAt:serverNow+3600000});
  return response(200,bodyFor(route));
 }});
 ui.ids.get('demo-start').events.click();await flush();
 const complete=ui.requests.find(r=>r.route==='/api/trial-session/recovery-complete');
 assert.ok(complete,'a valid challenge must reach server-side completion despite client clock skew');
 assert.equal(complete.options.headers['X-Trial-CSRF'],token);
 assert.equal(ui.ids.get('demo-end').disabled,false);
});

test('malformed recovery challenge responses never reach completion',async()=>{
 for(const fresh of [{challenge:'wrong',expiresAt:Date.now()+30000},{challenge:token,expiresAt:0},{challenge:token,expiresAt:-1},{challenge:token,expiresAt:'tomorrow'},{challenge:token,expiresAt:1.5}]){
  const ui=mockUI({responder:route=>route==='/api/trial-session/bootstrap'?response(403,{}):route==='/api/trial-session/recovery-challenge'?response(200,fresh):response(200,bodyFor(route))});
  ui.ids.get('demo-start').events.click();await flush();
  assert.equal(ui.requests.some(r=>r.route==='/api/trial-session/recovery-complete'),false);
  assert.equal(ui.ids.get('demo-end').disabled,true);
 }
});

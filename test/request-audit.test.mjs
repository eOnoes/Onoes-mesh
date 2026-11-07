import test from 'node:test';
import assert from 'node:assert/strict';
import {requestAudit,auditReason} from '../lib/request-audit.mjs';
test('denial audit excludes query, path secrets, cookies and raw header values',()=>{
  const secret='SECRET_MUST_NOT_LOG';
  for(const url of ['/api/tasks?token='+secret,'/'+secret,'https://user:'+secret+'@host/','/api/workroom/'+secret+'/progress']){
    const audit=requestAudit({method:'POST',url,headers:{host:secret,origin:secret,cookie:secret,authorization:secret,'x-forwarded-host':secret}});
    assert.ok(!JSON.stringify(audit).includes(secret));assert.equal(audit.originPresent,true);
  }
  assert.equal(auditReason('origin-mismatch:'+secret),'origin-mismatch');
});
test('audit preserves useful known route and action without entity identity',()=>{
  assert.equal(requestAudit({method:'PATCH',url:'/api/workroom/card123/progress?key=value',headers:{}}).url,'/api/workroom/:id/progress');
  assert.equal(requestAudit({method:'GET',url:'/api/health',headers:{}}).url,'/api/health');
});

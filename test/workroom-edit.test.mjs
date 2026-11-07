import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {saveCardBrief} from '../public/workroom-edit.mjs';

test('metadata save cannot promote stale goal inputs to a newer progress revision over HTTP',async()=>{
  const previous=process.env.MESH_STANDALONE;process.env.MESH_STANDALONE='1';
  const app=await startApp({dataDir:'data/card-edit-'+randomUUID(),relayEnabled:false});
  const headers={Origin:app.url,'Content-Type':'application/json'};
  try{
    const b=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});
    assert.equal(b.status,201);const proof=await b.json();headers.Cookie=b.headers.get('set-cookie').split(';')[0];headers['X-Trial-CSRF']=proof.csrfToken;
    const query=async(route,options={})=>{const r=await fetch(app.url+route,{...options,headers});const body=await r.json();if(!r.ok)throw Object.assign(Error(body.error||'Request rejected'),{status:r.status});return body;};
    assert.equal((await fetch(app.url+'/workroom-edit.mjs')).status,200);
    const {task:created}=await query('/api/tasks',{method:'POST',body:JSON.stringify({title:'Disposable concurrent editor',description:'No execution'})});
    const {task:older}=await query('/api/workroom/'+created.id);
    const draft={goal:'Older unsaved draft',checklist:[],result:'',evidence:'',reviewer:'',decision:'pending'};
    const progressBody=t=>({...draft,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
    const {task:newer}=await query('/api/workroom/'+created.id+'/progress',{method:'PATCH',body:JSON.stringify({...progressBody(older),goal:'Newer saved goal'})});
    const edited=await saveCardBrief(older,{project:'Changed project',criteria:older.workroom.criteria,owner:older.workroom.owner,stage:older.workroom.stage,team:older.workroom.team,revision:older.workroom.revision},query);
    assert.equal(edited.progress.revision,older.progress.revision);
    assert.equal(edited.workroom.project,'Changed project');
    await assert.rejects(query('/api/workroom/'+created.id+'/progress',{method:'PATCH',body:JSON.stringify(progressBody(edited))}),error=>error.status===409);
    const {task:after}=await query('/api/workroom/'+created.id);
    assert.equal(after.progress.goal,'Newer saved goal');assert.equal(after.progress.revision,newer.progress.revision);
    assert.equal(draft.goal,'Older unsaved draft');
    // Once the operator deliberately reopens current data, a new edit can save normally.
    const {task:resolved}=await query('/api/workroom/'+created.id+'/progress',{method:'PATCH',body:JSON.stringify(progressBody(after))});
    assert.equal(resolved.progress.goal,draft.goal);
    const normal=await saveCardBrief(resolved,{...resolved.workroom,project:'Another project',revision:resolved.workroom.revision},async(route,options)=>{
      const body=JSON.parse(options.body);
      return query(route,{...options,body:JSON.stringify({project:body.project,criteria:body.criteria,owner:body.owner,stage:body.stage,team:body.team,revision:body.revision})});
    });
    const {task:ordinary}=await query('/api/workroom/'+created.id+'/progress',{method:'PATCH',body:JSON.stringify({...progressBody(normal),goal:'Ordinary combined edit'})});
    assert.equal(ordinary.workroom.project,'Another project');assert.equal(ordinary.progress.goal,'Ordinary combined edit');
    const {task:approved}=await query('/api/workroom/'+created.id+'/progress',{method:'PATCH',body:JSON.stringify({
      ...progressBody(ordinary),checklist:[{id:'checked',text:'Synthetic acceptance check',status:'done'}],
      result:'Synthetic test result',evidence:'Synthetic test evidence',reviewer:'test-reviewer',decision:'approved'
    })});
    assert.equal(approved.progress.decision,'approved');
    const {project,criteria,owner,stage,team,revision}=approved.workroom;
    const reviewedEdit=await saveCardBrief(approved,{project,criteria:criteria+' revised',owner,stage,team,revision},query);
    const {task:revised}=await query('/api/workroom/'+created.id+'/progress',{method:'PATCH',body:JSON.stringify({
      ...progressBody(reviewedEdit),goal:'Revised goal after review',checklist:approved.progress.checklist,
      result:approved.progress.result,evidence:approved.progress.evidence,reviewer:approved.progress.reviewer,decision:'pending'
    })});
    assert.equal(revised.progress.goal,'Revised goal after review');assert.equal(revised.progress.decision,'pending');
    await assert.rejects(query('/api/workroom/'+created.id,{method:'PATCH',body:JSON.stringify({
      project:revised.workroom.project,criteria:revised.workroom.criteria,owner:'echo',stage:'done',team:revised.workroom.team,revision:revised.workroom.revision
    })}),error=>error.status===409);
  }finally{await app.close();if(previous===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=previous;}
});

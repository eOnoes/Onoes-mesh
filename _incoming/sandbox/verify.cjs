const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawn, spawnSync} = require('node:child_process');
const root = process.cwd();
const artifacts = path.join(root,'.verification');
fs.mkdirSync(artifacts,{recursive:true});
const sleep = ms => new Promise(r => setTimeout(r,ms));
let server, browser, baseline, baselineBytes, handoffBytes, sessionId;
const pending = new Map();
const browserErrors = [], requests = [];
let sequence = 0;
let pipeBuffer = '';
function receive(msg) {
  if(msg.id) { const p=pending.get(msg.id); if(p){pending.delete(msg.id); msg.error?p.reject(Error(JSON.stringify(msg.error))):p.resolve(msg.result);} }
  else if(msg.method==='Runtime.exceptionThrown') browserErrors.push(msg.params.exceptionDetails);
  else if(msg.method==='Runtime.consoleAPICalled' && msg.params.type==='error') browserErrors.push(msg.params.args);
  else if(msg.method==='Network.requestWillBeSent') requests.push(msg.params.request.url);
}
function startServer() {
  server = spawn('python',['-B','server.py'],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
  server.stdout.on('data', b => fs.appendFileSync(path.join(artifacts,'server-tests.log'),b));
  server.stderr.on('data', b => fs.appendFileSync(path.join(artifacts,'server-tests.log'),b));
}
async function stopServer() {
  if (!server || server.exitCode !== null || server.signalCode !== null) return;
  const stopped = new Promise(r => server.once('exit',r));
  if (process.platform === 'win32') {
    // The Windows venv launcher starts a child; stop only our spawned tree.
    const result = spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,encoding:'utf8'});
    if (result.status !== 0 && server.exitCode === null && server.signalCode === null) {
      throw Error('Could not stop verification server: '+(result.stderr || result.stdout));
    }
  } else server.kill();
  await stopped;
}
async function until(fn, label) {
  for(let i=0;i<100;i++) { try { if(await fn()) return; } catch {} await sleep(100); }
  throw Error('Timed out: '+label);
}
async function state() { const r=await fetch('http://127.0.0.1:8771/api/state'); assert.equal(r.status,200); return r.json(); }
function cdp(method,params={}) {
  const id=++sequence;
  return new Promise((resolve,reject) => { pending.set(id,{resolve,reject}); browser.stdio[3].write(JSON.stringify({id,method,params,...(sessionId ? {sessionId} : {})})+'\0'); });
}
async function evaluate(expression) {
  const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function click(selector) {
  const rect=await evaluate(`(() => { const el=document.querySelector(${JSON.stringify(selector)}); if(!el) throw Error('Missing '+${JSON.stringify(selector)}); const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
  await cdp('Input.dispatchMouseEvent',{type:'mousePressed',...rect,button:'left',clickCount:1});
  await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',...rect,button:'left',clickCount:1});
}
async function screenshot(name) {
  const result=await cdp('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(artifacts,name),Buffer.from(result.data,'base64'));
}
async function add(title) {
  await click('#open-set'); await sleep(250);
  await evaluate(`document.getElementById('add-title').value=${JSON.stringify(title)}; document.getElementById('add-note').value='Local verification only.';`);
  await click('#add-form button[type="submit"]');
  await until(async()=> (await state()).cards.some(c=>c.title===title),'page card saved');
  await until(()=>evaluate(`document.querySelector('[data-play]') !== null && !document.getElementById('settings').classList.contains('open')`),'added card opened');
  return (await state()).cards.find(c=>c.title===title);
}
async function startBrowser() {
  browser=spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',[
    '--headless=new','--remote-debugging-pipe',
    '--user-data-dir='+path.join(artifacts,'envelope-browser'),'--no-first-run','--no-default-browser-check',
    '--disable-background-networking','--disable-component-update','--disable-domain-reliability',
    '--disable-sync','--disable-default-apps','--metrics-recording-only',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','about:blank'
  ],{cwd:root,windowsHide:true,stdio:['ignore','ignore','ignore','pipe','pipe']});
  browser.stdio[4].setEncoding('utf8');
  browser.stdio[4].on('data',chunk=>{
    pipeBuffer += chunk; let boundary;
    while((boundary=pipeBuffer.indexOf('\0'))!==-1) { const packet=pipeBuffer.slice(0,boundary); pipeBuffer=pipeBuffer.slice(boundary+1); if(packet) receive(JSON.parse(packet)); }
  });
  const {targetId}=await cdp('Target.createTarget',{url:'about:blank'});
  const attached=await cdp('Target.attachToTarget',{targetId,flatten:true}); sessionId=attached.sessionId;
  await cdp('Page.enable'); await cdp('Runtime.enable'); await cdp('Network.enable');
}
async function handoff() {
  const response = await fetch('http://127.0.0.1:8771/api/handoff');
  assert.equal(response.status,200);
  assert.equal(response.headers.get('cache-control'),'no-store');
  return response.json();
}
async function requireFreePort() {
  const net = require('node:net');
  await new Promise((resolve,reject) => {
    const probe = net.createServer();
    probe.once('error',() => reject(Error('Stop the local app before verification: 127.0.0.1:8771 is busy.')));
    probe.listen(8771,'127.0.0.1',() => probe.close(resolve));
  });
}
function restoreOriginalData() {
  if (!baselineBytes) return;
  fs.writeFileSync(path.join(root,'data','cards.json'),baselineBytes);
  const ho = path.join(root,'data','handoff.json');
  if (handoffBytes !== null) fs.writeFileSync(ho,handoffBytes);
  else if (fs.existsSync(ho)) fs.unlinkSync(ho);
  assert.deepEqual(fs.readFileSync(path.join(root,'data','cards.json')),baselineBytes);
  assert.deepEqual(fs.existsSync(ho) ? fs.readFileSync(ho) : null,handoffBytes);
}
async function verifyHandoffSlice() {
  const http = require('node:http');
  const crypto = require('node:crypto');
  const lockedFiles = ['app.js','index.html'];
  const hashes = Object.fromEntries(lockedFiles.map(name => [name,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')]));
  // An older disk-only sample makes order observable and checks sample exclusion.
  // Existing real work is set aside until restoration; exactly one real add is made.
  const older = {id:'verification-older-sample',header:'unfiled',title:'Older verification sample',note:'Temporary ordering fixture.',who:'Echo',added:'2000-01-01T00:00:00Z',state:'ready',line:'sample only',sample:true,sampleState:'ready',pinned:false,trashedAt:null};
  assert.ok(!baseline.cards.some(c => c.id === older.id));
  const staged = {...baseline,cards:[...baseline.cards.filter(c => c.sample),older]};
  fs.writeFileSync(path.join(root,'data','cards.json'),JSON.stringify(staged,null,2)+'\n');
  const ho = path.join(root,'data','handoff.json');
  if (fs.existsSync(ho)) fs.unlinkSync(ho);
  startServer(); await until(state,'handoff server startup');
  assert.deepEqual(await handoff(),{state:'none'},'sample ready is not a handoff');
  assert.equal(fs.existsSync(ho),false,'GET none creates no handoff file');
  const outside = await fetch('http://127.0.0.1:8771/api/handoff',{headers:{Origin:'https://example.invalid'}});
  assert.equal(outside.status,403,'outside Origin rejected on GET');
  const badHost = await new Promise((resolve,reject) => {
    const request = http.get({hostname:'127.0.0.1',port:8771,path:'/api/handoff',headers:{Host:'localhost:8771'}},response => { response.resume(); response.on('end',() => resolve(response.statusCode)); });
    request.on('error',reject);
  });
  assert.equal(badHost,403,'noncanonical Host rejected on GET');
  console.log('PASS: GET none, sample exclusion, local Host/Origin guards.');
  await startBrowser();
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:'http://127.0.0.1:8771/'});
  await until(()=>evaluate(`document.querySelector('[data-header="unfiled"]') !== null`),'to-do render');
  const added = await add('Handoff verification '+Date.now());
  assert.equal(added.header,'unfiled'); assert.equal(added.state,'idle'); assert.equal(added.sample,false);
  assert.equal(added.line,'unfiled'); assert.equal(added.note,'Local verification only.');
  const saved = await state();
  assert.deepEqual(saved.headers,baseline.headers,'add invents no headers');
  assert.equal(saved.cards.length,staged.cards.length+1,'exactly one real card added');
  assert.deepEqual(saved.cards.filter(c=>c.id!==added.id),staged.cards,'existing fixture cards unchanged');
  async function assertNewestFirst() {
    const ids = await evaluate(`Array.from(document.querySelector('[data-header="unfiled"]').closest('.trunk').querySelectorAll('.nest [data-card]')).map(b=>b.dataset.card)`);
    assert.equal(ids[0],added.id,'new card is first under Unfiled');
    assert.ok(ids.indexOf(older.id)>0,'older sample follows the new card');
  }
  await assertNewestFirst();
  assert.deepEqual(await handoff(),{state:'none'},'idle add is not a handoff');
  await stopServer(); startServer(); await until(state,'restart after add');
  assert.deepEqual((await state()).cards.find(c=>c.id===added.id),added,'entire added card survives restart');
  await cdp('Page.reload');
  await until(()=>evaluate(`document.querySelector('[data-header="unfiled"]') !== null`),'unfiled after restart');
  await click('[data-header="unfiled"]'); await assertNewestFirst();
  await click(`[data-card="${added.id}"]`);
  assert.equal(await evaluate(`document.querySelector('.open-note .note').textContent`),'Local verification only.');
  console.log('PASS: one form POST adds Unfiled newest-first; full card and displayed order survive restart.');
  async function expectHandoff(expectedState) {
    const expected = {id:added.id,title:added.title,state:expectedState};
    assert.deepEqual(await handoff(),expected);
    assert.deepEqual(JSON.parse(fs.readFileSync(ho,'utf8')),expected,'GET matches the disk handoff');
  }
  async function action(name,expectedState) {
    await click(`[data-${name}="${added.id}"]`);
    await until(async()=> (await state()).cards.find(c=>c.id===added.id).state===expectedState,name);
    await expectHandoff(expectedState);
  }
  await action('play','ready');
  await stopServer(); startServer(); await until(state,'restart ready'); await expectHandoff('ready');
  await action('pause','paused');
  await stopServer(); startServer(); await until(state,'restart paused'); await expectHandoff('paused');
  await action('trash','trash');
  await stopServer(); startServer(); await until(state,'restart trash'); await expectHandoff('trash');
  assert.equal(requests.filter(url=>url==='http://127.0.0.1:8771/api/cards').length,1,'one add request');
  assert.deepEqual(browserErrors,[],'no browser exceptions');
  assert.deepEqual(requests.filter(url=>!url.startsWith('http://127.0.0.1:8771/')),[],'all page requests stay local');
  console.log('PASS: GET ready, paused, trash match disk and each survive restart.');
  await stopServer(); restoreOriginalData();
  for (const name of lockedFiles) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex'),hashes[name],name+' unchanged');
  const report = {url:'http://127.0.0.1:8771/api/handoff',checks:['No handoff returns state none','Ready sample excluded','Outside Origin and noncanonical Host rejected','Exactly one form POST adds an idle non-sample card under Unfiled','Newest-first compared with older disk-only sample','Full added card and displayed order survive process restart','GET id/title/ready matches disk and survives restart','GET id/title/paused matches disk and survives restart','GET id/title/trash matches disk and survives restart','No browser errors or outside page requests','Original cards and handoff restored byte-for-byte','app.js and index.html unchanged'],addRequests:1,testCardsRemoved:true,originalDataRestored:true,lockedFileHashes:hashes};
  fs.writeFileSync(path.join(artifacts,'handoff-results.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}

(async()=>{
  await requireFreePort();
  const initialHandoff=path.join(root,'data','handoff.json');
  handoffBytes=fs.existsSync(initialHandoff)?fs.readFileSync(initialHandoff):null;
  baselineBytes=fs.readFileSync(path.join(root,'data','cards.json'));
  baseline=JSON.parse(baselineBytes);
  if (process.argv.includes('--handoff')) { await verifyHandoffSlice(); return; }
  startServer(); await until(state,'server startup');
  console.log('Saved baseline; verification will restore the original cards and handoff.');
  await startBrowser();
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:'file:///'+path.join(root,'reference','todo_tab.html').replaceAll('\\','/')});
  await until(()=>evaluate(`document.querySelector('[data-card="shape"]') !== null`),'reference render');
  await screenshot('reference-desktop.png');
  browserErrors.length=0; requests.length=0;
  await cdp('Page.navigate',{url:'http://127.0.0.1:8771/'});
  await until(()=>evaluate(`document.querySelector('[data-card="shape"]') !== null`),'live page render');
  await screenshot('live-desktop.png');
  assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('[data-header]')).map(b=>b.textContent.trim())`),['[ Category 0 ]','[ Mesh ]','[ Models ]','[ Forge ]','[ Crew ]']);
  assert.equal(await evaluate(`document.querySelectorAll('[data-play]').length`),0,'no sample Play');
  const original=fs.readFileSync('reference/todo_tab.html','utf8'), live=fs.readFileSync('index.html','utf8');
  assert.equal(live.match(/<style>[\s\S]*?<\/style>/)[0],original.match(/<style>[\s\S]*?<\/style>/)[0],'all original styles retained');
  assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('[data-section]')).map(b=>b.dataset.section)`),['overview','workroom','relay','todo','log']);
  await click('[data-header="models"]');
  assert.equal(await evaluate(`document.querySelectorAll('[data-header][aria-expanded="true"]').length`),1);
  assert.equal(await evaluate(`document.querySelectorAll('.open-note').length`),0);
  await click('[data-card="ngram"]'); await click('[data-card="iq3"]');
  assert.equal(await evaluate(`document.querySelectorAll('.open-note').length`),1);
  for(const section of ['overview','workroom','relay','log']) {
    await click(`[data-section="${section}"]`);
    await until(()=>evaluate(`document.getElementById('crumb').textContent===${JSON.stringify(section)}`),'section navigation');
    assert.equal(await evaluate(`document.getElementById('stage').hidden && !document.getElementById('pages').hidden && !document.getElementById('page-${section}').hidden`),true);
    assert.equal(await evaluate(`document.querySelectorAll('.page:not([hidden])').length`),1);
    assert.equal(await evaluate(`document.querySelectorAll('[data-section][aria-selected="true"]').length`),1);
    await screenshot(`envelope-${section}-desktop.png`);
  }
  await click('[data-section="overview"]'); await click('#goal');
  assert.equal(await evaluate(`!document.getElementById('goal-body').hidden`),true);
  await click('#goal'); assert.equal(await evaluate(`document.getElementById('goal-body').hidden`),true);
  await click('#open-set'); await sleep(250);
  assert.equal(await evaluate(`document.activeElement.id`),'tog-tags');
  await click('#tog-tags'); assert.equal(await evaluate(`Array.from(document.querySelectorAll('.page .tag')).every(t=>t.hidden)`),true);
  await click('#tog-tags'); await click('#tog-compact');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('#page-overview .facts p')).display`),'none');
  await click('#tog-compact');
  const beforeDead=await state(), requestCount=requests.length;
  await click('#page-settings [data-live="off"]');
  assert.equal(requests.length,requestCount,'inactive config sends no request');
  assert.deepEqual(await state(),beforeDead,'inactive config changes no cards');
  await screenshot('envelope-config-desktop.png');
  await click('#close-set'); await sleep(250);
  await click('[data-section="workroom"]'); await click('[data-work-filter="wait"]');
  assert.equal(await evaluate(`document.querySelectorAll('[data-work-state]:not([hidden])').length`),2);
  await click('[data-work-state="wait"]'); assert.equal(await evaluate(`!document.getElementById('card-detail').hidden`),true);
  await click('[data-work-filter="done"]');
  assert.equal(await evaluate(`document.querySelectorAll('[data-work-state]:not([hidden])').length`),1);
  assert.equal(await evaluate(`document.getElementById('card-detail').hidden`),true);
  await click('[data-work-state="done"]'); await screenshot('envelope-workroom-detail.png');
  await click('[data-work-filter="all"]');
  await click('[data-section="relay"]');
  await evaluate(`document.getElementById('draft').value='<b>Local relay verification</b>'`);
  await click('#composer button[type="submit"]');
  assert.equal(await evaluate(`document.querySelector('#thread article:last-child p').textContent`),'<b>Local relay verification</b>');
  assert.equal(await evaluate(`document.querySelector('#thread article:last-child b')===null`),true,'message rendered as text');
  const beforeLive=requests.length;
  await click('#composer [data-live="off"]'); assert.equal(requests.length,beforeLive,'live send sends no request');
  await click('[data-section="log"]'); await click('[data-section="relay"]');
  assert.equal(await evaluate(`document.querySelectorAll('#thread article').length`),3,'local message survives page navigation');
  await cdp('Page.reload'); await until(()=>evaluate(`document.querySelectorAll('#thread article').length===2 && document.getElementById('crumb').textContent==='relay'`),'relay reload and hash');
  await cdp('Page.navigate',{url:'http://127.0.0.1:8771/'}); await until(()=>evaluate(`document.getElementById('crumb').textContent==='to-do' && document.querySelector('[data-card="shape"]') !== null`),'default to-do');

  await click('[data-section="todo"]');
  const first=await add('Local verification A');
  assert.equal(first.header,'unfiled'); assert.equal(first.state,'idle');
  if(!handoffBytes) assert.equal(fs.existsSync(path.join(root,'data','handoff.json')),false);
  await stopServer(); startServer(); await until(state,'server restart');
  await cdp('Page.reload');
  await until(()=>evaluate(`document.querySelector('[data-header="unfiled"]') !== null`),'unfiled survives restart');
  await click('[data-header="unfiled"]'); await click(`[data-card="${first.id}"]`);
  assert.equal(await evaluate(`document.querySelector('.open-note .note').textContent`),'Local verification only.');
  await click(`[data-play="${first.id}"]`);
  await until(async()=> (await state()).cards.find(c=>c.id===first.id).state==='ready','first Play');
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'data','handoff.json'),'utf8')),{id:first.id,title:first.title,state:'ready'});
  const second=await add('Local verification B');
  await click(`[data-play="${second.id}"]`);
  await until(async()=> (await state()).cards.find(c=>c.id===second.id).state==='ready','second Play');
  let saved=await state();
  assert.equal(saved.cards.find(c=>c.id===first.id).state,'paused');
  assert.equal(saved.cards.find(c=>c.id===first.id).trashedAt,null);
  assert.equal(saved.cards.filter(c=>!c.sample && c.state==='ready').length,1);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'data','handoff.json'),'utf8')),{id:second.id,title:second.title,state:'ready'});
  await screenshot('live-handoff.png');
  await stopServer(); startServer(); await until(state,'restart with handoff');
  saved=await state(); assert.equal(saved.cards.find(c=>c.id===first.id).state,'paused'); assert.equal(saved.cards.find(c=>c.id===second.id).state,'ready');
  await click(`[data-pause="${second.id}"]`);
  await until(async()=> (await state()).cards.find(c=>c.id===second.id).state==='paused','explicit Pause');
  assert.equal(JSON.parse(fs.readFileSync(path.join(root,'data','handoff.json'),'utf8')).state,'paused');
  await click(`[data-trash="${second.id}"]`);
  await until(async()=> (await state()).cards.find(c=>c.id===second.id).state==='trash','Trash');
  await click('#open-set'); await sleep(250); await click('[data-filter="trash"]'); await click('#close-set'); await sleep(250);
  await click(`[data-card="${second.id}"]`); await click(`[data-restore="${second.id}"]`);
  await until(async()=> (await state()).cards.find(c=>c.id===second.id).state==='idle','Recover');
  const sampleResponse=await fetch('http://127.0.0.1:8771/api/cards/shape/play',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  assert.equal(sampleResponse.status,400,'sample Play rejected by backend');
  const external=await fetch('http://127.0.0.1:8771/api/cards',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://example.invalid'},body:JSON.stringify({title:'Reject outside origin'})});
  assert.equal(external.status,403);
  const traversal=await fetch('http://127.0.0.1:8771/data/cards.json'); assert.equal(traversal.status,404,'data not publicly served');
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.deepEqual(browserErrors,[],'no desktop JS exceptions');
  assert.deepEqual(requests.filter(url=>!url.startsWith('http://127.0.0.1:8771/')),[],'desktop requests stay local');
  await cdp('Page.navigate',{url:'file:///'+path.join(root,'reference','todo_tab.html').replaceAll('\\','/')});
  await until(()=>evaluate(`document.querySelector('[data-card="shape"]') !== null`),'mobile reference');
  await screenshot('reference-mobile.png'); browserErrors.length=0; requests.length=0;
  await cdp('Page.navigate',{url:'http://127.0.0.1:8771/'}); await until(()=>evaluate(`document.querySelector('[data-header="mesh"]') !== null`),'mobile render');
  for(const section of ['overview','workroom','relay','log','todo']) {
    await click('#open-menu'); await sleep(250); await click(`[data-section="${section}"]`); await sleep(250);
    assert.equal(await evaluate(`document.getElementById('menu').inert && !document.getElementById('menu').classList.contains('open')`),true);
    assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`),true,'no mobile horizontal overflow');
    await screenshot(`envelope-${section}-mobile.png`);
    await click('#open-set'); await sleep(250);
    assert.equal(await evaluate(`!document.getElementById('settings').inert`),true);
    await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'}); await sleep(250);
    assert.equal(await evaluate(`document.getElementById('settings').inert`),true);
  }
  await click('#open-menu'); await sleep(250); await click('[data-section="todo"]'); await sleep(250);
  assert.equal(await evaluate(`document.getElementById('menu').classList.contains('open')`),false);
  await click('#open-set'); await sleep(250);
  assert.equal(await evaluate(`!document.getElementById('settings').inert`),true);
  await click('#close-set'); await sleep(250); await screenshot('live-mobile.png');
  assert.deepEqual(browserErrors,[],'no browser JS exceptions');
  assert.deepEqual(requests.filter(url=>!url.startsWith('http://127.0.0.1:8771/')),[],'page requests stay local');
  await stopServer();
  fs.writeFileSync(path.join(root,'data','cards.json'),baselineBytes);
  const restoredHandoff=path.join(root,'data','handoff.json');
  if(handoffBytes) fs.writeFileSync(restoredHandoff,handoffBytes); else if(fs.existsSync(restoredHandoff)) fs.unlinkSync(restoredHandoff);
  assert.deepEqual(fs.readFileSync(path.join(root,'data','cards.json')),baselineBytes);
  // Also restored in finally, including after a failed assertion.
  const report = {
    url:'http://127.0.0.1:8771/',
    checks:['Browser renders live page','Original stylesheet unchanged','Exact sample headers and original sections','One header and one card open','All five sections opened at desktop and mobile sizes','Overview expand/collapse','Workroom filters and detail','Relay keep local as text, navigation and reload','Inactive controls make no requests','Fixture and compact toggles','Section hashes survive reload','Added via page form and survived process restart','Play wrote id/title/ready handoff','Second Play paused first without trash','Ready and paused states survived restart','Explicit Pause updated handoff','Trash recoverable','Sample Play rejected','Outside-origin writes rejected','Data files not served','Mobile nav and config','No browser exceptions or outside page requests'],
    testCardsRemoved:true, originalDataRestored:true
  };
  fs.writeFileSync(path.join(artifacts,'envelope-results.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
  await stopServer();
  restoreOriginalData();
  if(browser && browser.exitCode === null && browser.signalCode === null) {
    sessionId=null; await Promise.race([cdp('Browser.close').catch(()=>{}),sleep(1000)]); browser.kill();
    browser.stdio[3].destroy(); browser.stdio[4].destroy();
  }
});


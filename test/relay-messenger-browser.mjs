import {createServer} from 'node:http';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
import {once} from 'node:events';
const {chromium}=await import(process.env.M5_NODES_PLAYWRIGHT ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'file:///C:/Users/eMitchell109/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const root=fileURLToPath(new URL('..',import.meta.url));
const proof=process.env.MESH_BROWSER_PROOF_DIR||resolve(root,'data','relay-messenger-browser-'+randomUUID());
await mkdir(proof,{recursive:true});
function boot(createRelayChat){
  document.querySelectorAll('[role="tabpanel"]').forEach(p=>p.hidden=true);
  document.getElementById('panel-relay').hidden=false;
  const fakeViewport=Object.assign(new EventTarget(),{height:innerHeight,offsetTop:0});
  Object.defineProperty(window,'visualViewport',{configurable:true,value:fakeViewport});
  window.fixtureWrites=[];window.fixtureReads=[];
  const a='11111111-1111-4111-8111-111111111111',b='22222222-2222-4222-8222-222222222222';
  const request=async(route,options)=>{
    window.fixtureReads.push(route);
    if(route==='/api/relay/native/api/agents')return [{id:'echo',name:'Echo',conversation_id:'echo-session',status:'idle'},{id:'cyony',name:'Cyony',conversation_id:'cyony-session',status:'idle'}];
    if(route==='/api/relay/codex/status')return {configured:true,readOnly:false};
    if(route==='/api/relay/codex/catalog')return {project:{id:'33333333-3333-4333-8333-333333333333',label:'Fixture project'},conversations:[{id:a,title:'Fixture A',status:'idle'},{id:b,title:'Fixture B',status:'idle'}],nextCursor:null};
    if(route==='/api/relay/codex/history'){
      const {threadId}=JSON.parse(options.body);
      return {conversation:{id:threadId,title:threadId===a?'Fixture A':'Fixture B',status:'idle'},groups:[{id:'turn-'+threadId,messages:Array.from({length:30},(_,i)=>({id:threadId+'-'+i,role:i%2?'assistant':'user',text:'Native fixture '+i+'. '+('Readable synthetic message. '.repeat(14))})),olderItemCursor:null}],olderTurnCursor:null};
    }
    if(route.includes('/messages?')){
      const older=route.includes('before='),first=older?91:101,count=older?10:20;
      return {messages:Array.from({length:count},(_,i)=>({id:first+i,k:i%2?'ag':'you',t:'Echo message '+(first+i)+'. '+('Synthetic history only. '.repeat(15))})),oldest_id:first,newest_id:first+count-1,has_more:!older};
    }
    if(options?.method==='POST'){window.fixtureWrites.push(route);throw Error('Unexpected synthetic write: '+route);}
    if(route==='/relay/api/mesh-capabilities')return {taskSessionBinding:1};
    return {};
  };
  window.fixtureChat=createRelayChat({request});window.fixtureChat.setAvailable(true);
  const lock=document.getElementById('demo-end');lock.disabled=false;
  lock.addEventListener('click',()=>window.fixtureChat.clear());
  window.fixtureBack=0;document.getElementById('tab-overview').addEventListener('click',()=>window.fixtureBack++);
}
const setup='<script type="module">import {createRelayChat} from "/chat.mjs";('+boot.toString()+')(createRelayChat);</script>';
const markup=(await readFile(root+'/public/index.html','utf8')).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace('</body>',setup+'</body>');
const server=createServer(async(req,res)=>{
  try{
    const pathname=new URL(req.url,'http://fixture').pathname;
    if(pathname==='/'){res.setHeader('Content-Type','text/html;charset=utf-8');res.end(markup);return;}
    if(!/^\/(?:shared\/)?[a-zA-Z0-9_.-]+$/.test(pathname)){res.writeHead(404);res.end();return;}
    const aliases={'/shared/tokens.css':'shared/tokens.css','/mesh-tokens-v3.css':'shared/tokens.css','/mesh-design-v3.css':'public/styles.css'};
    const file=resolve(root,aliases[pathname]||'public'+pathname),body=await readFile(file);
    res.setHeader('Content-Type',{'.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[extname(file)]||'application/octet-stream');res.end(body);
  }catch{res.writeHead(404);res.end();}
});
let browser;
try{
  server.listen(0,'127.0.0.1');await once(server,'listening');
  browser=await chromium.launch({headless:true,executablePath:process.env.M5_NODES_CHROMIUM});
  const results=[];
  for(const [width,height] of [[390,844],[844,390],[1440,900]]){
    const page=await browser.newPage({viewport:{width,height}});
    page.setDefaultTimeout(6000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:'+server.address().port);
    const badge=page.locator('#relay-agent-toggle'),menus=page.locator('#relay-history-toggle');
    await badge.waitFor();assert.equal(await badge.textContent(),'Choose agent');
    const choose=async id=>{
      await badge.click();await page.locator('#relay-agent-drawer[open]').waitFor();
      await page.locator('#relay-agent-drawer button[data-agent-id="'+id+'"]').click();
      await page.locator('#relay-agent-drawer').waitFor({state:'hidden'});
    };
    await choose('echo');await page.locator('#relay-chat .chat-msg').first().waitFor();
    assert.equal(await badge.textContent(),'Echo');
    const input=page.locator('#relay-text');await input.fill('Unsent Echo draft');
    const geometry=await page.locator('.relay-messenger').evaluate(frame=>{
      const f=frame.getBoundingClientRect(),c=document.getElementById('relay-form').getBoundingClientRect(),t=document.getElementById('relay-chat').getBoundingClientRect();
      return {top:f.top,height:f.height,bottom:f.bottom,composerBottom:c.bottom,transcriptHeight:t.height,width:document.documentElement.scrollWidth};
    });
    assert.ok(Math.abs(geometry.top)<2&&Math.abs(geometry.height-height)<2,JSON.stringify(geometry));
    assert.ok(geometry.composerBottom<=height+2&&geometry.transcriptHeight>60,JSON.stringify(geometry));
    assert.ok(geometry.width<=width+1,'Horizontal overflow');
    await choose('nims');assert.equal(await badge.textContent(),'Nims');
    await menus.click();await page.waitForFunction(()=>!document.getElementById('nims-native-conversation').disabled);
    await page.locator('#nims-native-conversation').selectOption('11111111-1111-4111-8111-111111111111');
    await page.locator('#relay-history-drawer').waitFor({state:'hidden'});
    const native=page.locator('[data-nims-history]'),nativeInput=page.locator('[data-nims-text]');
    await native.locator('article').first().waitFor();await nativeInput.fill('Unsent Nims draft');
    const nativeGeometry=await native.evaluate(el=>({height:el.clientHeight,scroll:el.scrollHeight,top:el.scrollTop,body:el.parentElement.getBoundingClientRect().height,root:document.getElementById('relay-nims-chats').getBoundingClientRect().height}));
    console.log(JSON.stringify({width,nativeGeometry}));
    await page.screenshot({path:proof+'/native-layout-'+width+'.png'});
    await native.evaluate(el=>el.scrollTop=0);
    const latest=page.locator('#relay-messenger-latest');await latest.waitFor({state:'visible',timeout:2000});await latest.click();
    await page.waitForFunction(()=>{const e=document.querySelector('[data-nims-history]');return e.scrollHeight-e.clientHeight-e.scrollTop<3;});
    await menus.click();await page.locator('[data-nims-new]').click();
    await page.locator('#relay-history-drawer').waitFor({state:'hidden'});
    await page.locator('[data-nims-new-form]').waitFor({state:'visible'});
    await page.locator('[data-nims-cancel-new]').click();
    assert.equal(await nativeInput.inputValue(),'Unsent Nims draft');
    await choose('echo');assert.equal(await input.inputValue(),'Unsent Echo draft');
    const ordinary=page.locator('#relay-chat');
    await ordinary.evaluate(el=>el.scrollTop=0);await latest.waitFor({state:'visible',timeout:2000});await latest.click();
    await page.waitForFunction(()=>{const e=document.getElementById('relay-chat');return e.scrollHeight-e.clientHeight-e.scrollTop<3;});
    await ordinary.evaluate(el=>el.scrollTop=150);await menus.click();await page.keyboard.press('Escape');
    await page.locator('#relay-history-drawer').waitFor({state:'hidden'});
    assert.equal(await ordinary.evaluate(e=>e.scrollTop),150,'Opening history must not move reader');
    await page.waitForFunction(()=>document.getElementById('relay-history-toggle').getAttribute('aria-expanded')==='false');
    assert.equal(await menus.getAttribute('aria-expanded'),'false');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'relay-history-toggle');
    await menus.click();await page.locator('#relay-chat-older').click();await page.keyboard.press('Escape');
    await page.waitForFunction(()=>document.querySelectorAll('#relay-chat .chat-msg').length===30);
    assert.ok(await ordinary.evaluate(e=>e.scrollTop)>150,'Older history preserves passage after prepend');
    await page.evaluate(()=>{visualViewport.height=Math.min(360,innerHeight);visualViewport.dispatchEvent(new Event('resize'));});
    await page.waitForFunction(()=>Math.abs(document.querySelector('.relay-messenger').getBoundingClientRect().height-Math.min(360,innerHeight))<2);
    const keyboard=await page.locator('#relay-form').boundingBox();
    assert.ok(keyboard.y+keyboard.height<=Math.min(360,height)+2,'Composer rises with viewport');
    await page.evaluate(()=>{visualViewport.height=innerHeight;visualViewport.dispatchEvent(new Event('resize'));});
    await choose('nims');assert.equal(await nativeInput.inputValue(),'Unsent Nims draft');
    for(const theme of width===390?['dark','light']:['dark']){
      await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
      await page.screenshot({path:proof+'/synthetic-messenger-'+width+'-'+theme+'.png',fullPage:true});
    }
    await menus.click();await page.locator('#relay-messenger-lock').click();
    await page.waitForFunction(()=>document.getElementById('relay-agent-toggle').disabled);
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
    assert.equal(await badge.textContent(),'Choose agent');
    assert.equal(await page.locator('.relay-messenger-agents button').count(),0);
    assert.equal(await input.inputValue(),'');assert.equal(await nativeInput.inputValue(),'');
    assert.equal(await native.locator('article').count(),0);
    await menus.click();await page.getByRole('button',{name:'Back to Mesh',exact:true}).click();
    assert.equal(await page.evaluate(()=>window.fixtureBack),1,'Locked workspace navigation remains reachable');
    assert.equal(await page.evaluate(()=>window.fixtureWrites.length),0);
    assert.deepEqual(errors,[]);
    results.push({width,height,geometry,nativePickerWithoutLegacyEntry:true,bothJumpArrows:true,draftsPreserved:true,olderReadingPosition:true,keyboardCheck:'simulated visualViewport event, not physical keyboard',privacyCleared:true,newChatCancelledWithoutWrite:true,pageErrors:0});
    await page.close();
  }
  await writeFile(proof+'/BROWSER.json',JSON.stringify({passed:true,scope:'SYNTHETIC candidate: actual UI/core/DOM, local fixture requests only',liveServiceContact:false,modelCalls:0,results},null,2));
  console.log(JSON.stringify({passed:true,proof,results}));
}finally{await browser?.close();await new Promise(r=>server.close(r));}

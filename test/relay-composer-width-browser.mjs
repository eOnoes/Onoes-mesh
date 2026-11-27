import {createServer} from 'node:http';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
import {once} from 'node:events';
const {chromium}=await import(process.env.M5_NODES_PLAYWRIGHT ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'playwright');
const root=fileURLToPath(new URL('..',import.meta.url));
const proof=process.env.MESH_BROWSER_PROOF_DIR || resolve(root,'data','relay-width-browser-'+randomUUID());
await mkdir(proof,{recursive:true});
const setup=`<script type="module">
import {createRelayChat} from '/chat.mjs';
document.querySelectorAll('[role="tabpanel"]').forEach(p=>p.hidden=true);
document.getElementById('panel-relay').hidden=false;
window.fixturePosts=[];
const request=async (route,options)=>{
 if(options?.method==='POST'){window.fixturePosts.push(JSON.parse(options.body));return {ok:true};}
 if(route==='/api/relay/native/api/agents')return [{id:'echo',name:'Echo',conversation_id:'synthetic-session',status:'idle'}];
 if(route==='/relay/api/mesh-capabilities')return {taskSessionBinding:1};
 if(route.includes('/messages?'))return {messages:[{id:1,k:'ag',t:'Disposable browser fixture. No message reaches Echo.'}]};
 return {};
};
window.fixtureChat=createRelayChat({request});window.fixtureChat.setAvailable(true);
</script>`;
const markup=(await readFile(root+'/public/index.html','utf8')).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace('</body>',setup+'</body>');
const server=createServer(async(req,res)=>{
 try{
  const pathname=new URL(req.url,'http://fixture').pathname;
  if(pathname==='/'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(markup);return;}
  if(!/^\/[a-zA-Z0-9_./-]+$/.test(pathname)||pathname.includes('..')){res.writeHead(404);res.end();return;}
  const file=pathname==='/shared/tokens.css'?resolve(root,'shared/tokens.css'):resolve(root,'public','.'+pathname);
  const body=await readFile(file);
  res.setHeader('Content-Type',{'.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[extname(file)]||'application/octet-stream');res.end(body);
 }catch{res.writeHead(404);res.end();}
});
let browser;
try{
 server.listen(0,'127.0.0.1');await once(server,'listening');
 browser=await chromium.launch({headless:true,executablePath:process.env.M5_NODES_CHROMIUM});
 const results=[];
 for(const width of [390,574,1440]){
  const page=await browser.newPage({viewport:{width,height:900}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.locator('#relay-chat-agent').selectOption('echo');
  const input=page.locator('#relay-text'), send=page.locator('#relay-send'), status=page.locator('#relay-chat-status');
  await input.waitFor({state:'visible'});
  const long='p'.repeat(4000)+'KEEP THIS SUFFIX';
  await input.focus();await page.keyboard.insertText(long);
  assert.equal(await input.inputValue(),long,'browser insertion must not truncate pasted text');
  const bounds=await page.locator('#panel-relay').evaluate(panel=>{
   const outer=panel.parentElement,style=getComputedStyle(outer),box=outer.getBoundingClientRect(),p=panel.getBoundingClientRect();
   const c=document.getElementById('relay-text').getBoundingClientRect(),send=document.getElementById('relay-send').getBoundingClientRect();
   return {availableLeft:box.left+parseFloat(style.paddingLeft),availableRight:box.right-parseFloat(style.paddingRight),left:p.left,right:p.right,width:p.width,inputLeft:c.left,inputRight:c.right,sendLeft:send.left,sendRight:send.right,documentWidth:document.documentElement.scrollWidth};
  });
  assert.ok(bounds.left>=bounds.availableLeft-1 && bounds.right<=bounds.availableRight+1,
   'Long draft must keep Relay panel inside main content: '+JSON.stringify({viewport:width,...bounds}));
  assert.ok(bounds.inputLeft>=bounds.left && bounds.inputRight<=bounds.right+1,'Composer remains inside panel');
  assert.ok(bounds.sendLeft>=bounds.left && bounds.sendRight<=bounds.right+1,'Send remains inside panel');

  assert.equal(await send.isDisabled(),true);assert.match(await status.textContent(),/4016\/4000.*shorten/i);
  await page.evaluate(()=>window.fixtureChat.refresh());
  assert.equal(await input.inputValue(),long);assert.equal(await page.evaluate(()=>window.fixturePosts.length),0);
  await page.screenshot({path:proof+'/length-warning-'+width+'.png',fullPage:true});
  const valid='v'.repeat(3998)+'😀';await input.fill(valid);
  assert.equal(await send.isEnabled(),true);assert.doesNotMatch(await status.textContent(),/4016\/4000|shorten/i);
  await send.click();await page.waitForFunction(()=>window.fixturePosts.length===1);
  const sent=await page.evaluate(()=>window.fixturePosts[0]);assert.equal(sent.text,valid);
  assert.equal(await input.inputValue(),'');assert.deepEqual(errors,[]);
  results.push({width,retainedChars:long.length,actualBrowserInsertion:true,panelContained:true,sendContained:true,oversizeRequests:0,validSendChars:valid.length,exactSyntheticDelivery:true,pageErrors:errors.length});
  await page.close();
 }
 await writeFile(proof+'/BROWSER.json',JSON.stringify({passed:true,liveServiceContact:false,fixture:'actual Relay core, UI markup and styles; synthetic request function',results},null,2));
 console.log(JSON.stringify({passed:true,viewports:results,liveServiceContact:false}));
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}

const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('pwa.js', 'utf8');
function fixture() {
  const els = {}; for (const id of ['mesh-install','mesh-refresh','mesh-app-status','draft','goal-arm']) {
    els[id] = {value: '', textContent: '', disabled: false, handlers: {},
      addEventListener(n,fn) {this.handlers[n]=fn;}, getAttribute() {return 'false';}};
  }
  const storage = new Map([['relay-run','protected-run']]);
  const c = {document: {getElementById: id=>els[id],querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){}},
    navigator: {}, matchMedia:()=>({matches:false}), isSecureContext: true,
    busy:false, photoUploading:false, chatRun:null, staged:null, stagedPhoto:null,replyTo:null,ui:{editing:null},
    proactiveTimer:0, proactiveStream:null, proactiveSeq:-1, proactiveGap:false, startProactive(){}, stopProactive(){},
    roomBootstrap:Promise.resolve(), room:'room-one', chatRoom:()=>c.room,
    location:{href:'https://mesh.example:8450/#relay',replace(url){c.replaced=url;}},
    sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    fetch:async()=>({ok:true,headers:{get:()=> 'text/html'}}), armGoal:v=>{c.goal=v;},fitDraft(){},paintSlash(){},URL,Date,
    console, setTimeout};
  c.window={addEventListener(n,fn){c[n]=fn;}}; vm.createContext(c); vm.runInContext(source,c);
  return {c,els,storage};
}
(async()=>{
  let f=fixture(); f.els.draft.value='Do not submit this draft';
  assert.equal(await f.c.window.meshPwa.hardRefresh(),true);
  assert(f.c.replaced.includes('mesh-refresh=') && f.c.replaced.endsWith('#relay'));
  assert.equal(f.storage.get('relay-run'),'protected-run');
  let snap=JSON.parse(f.storage.get('mesh-refresh-draft-v1')); assert.equal(snap.text,'Do not submit this draft');
  f.els.draft.value=''; assert.equal(await f.c.window.meshPwa.restoreDraft(),true);
  assert.equal(f.els.draft.value,snap.text); assert(!f.storage.has('mesh-refresh-draft-v1'));
  for(const field of ['staged','stagedPhoto','replyTo','photoUploading','busy']) {
    f=fixture(); f.c[field]=true; assert.equal(await f.c.window.meshPwa.hardRefresh(),false); assert(!f.c.replaced);
  }
  f=fixture(); f.c.ui.editing='card'; assert.equal(await f.c.window.meshPwa.hardRefresh(),false);
  f=fixture(); f.c.chatRun='pending'; assert.equal(await f.c.window.meshPwa.hardRefresh(),false);
  f=fixture(); f.c.fetch=async()=>{throw Error('offline');}; f.els.draft.value='kept';
  assert.equal(await f.c.window.meshPwa.hardRefresh(),false);assert.equal(f.els.draft.value,'kept');assert(!f.c.replaced);
  f=fixture(); f.storage.set('mesh-refresh-draft-v1',JSON.stringify({room:'another',text:'wrong room'}));
  assert.equal(await f.c.window.meshPwa.restoreDraft(),false);assert.equal(f.els.draft.value,'');assert(f.storage.has('mesh-refresh-draft-v1'));
  f.c.room='another';assert.equal(await f.c.window.meshPwa.restoreDraft(),true);assert.equal(f.els.draft.value,'wrong room');
  f=fixture();await f.els['mesh-install'].handlers.click();assert(f.els['mesh-app-status'].textContent.includes('Chrome'));
  let prompted=false;f.c.beforeinstallprompt({preventDefault(){},prompt:async()=>{prompted=true;},userChoice:Promise.resolve({outcome:'accepted'})});
  await f.els['mesh-install'].handlers.click();assert(prompted);
  const listeners={};let fetched=0;
  const sw={self:{location:{origin:'https://mesh.example'},clients:{claim:async()=>{}},skipWaiting:async()=>{},addEventListener:(n,fn)=>listeners[n]=fn},
    URL,Response,fetch:async()=>{fetched++;throw Error('offline');}};
  vm.createContext(sw);vm.runInContext(fs.readFileSync('mesh-sw.js','utf8'),sw);
  let intercepted=false;listeners.fetch({request:{method:'POST',mode:'navigate',url:'https://mesh.example/api/send'},respondWith(){intercepted=true;}});assert(!intercepted);
  listeners.fetch({request:{method:'GET',mode:'cors',url:'https://mesh.example/api/history'},respondWith(){intercepted=true;}});assert(!intercepted);
  let response;listeners.fetch({request:{method:'GET',mode:'navigate',url:'https://mesh.example/'},respondWith(p){response=p;}});
  const offline=await response;assert.equal(offline.status,503);assert((await offline.text()).includes('does not keep an offline copy'));assert.equal(fetched,1);
  assert(!fs.readFileSync('mesh-sw.js','utf8').includes('caches.'));
  const manifest=JSON.parse(fs.readFileSync('manifest.webmanifest','utf8'));assert.equal(manifest.display,'standalone');assert.equal(manifest.start_url,'/#relay');
  for(const icon of manifest.icons){const b=fs.readFileSync('.'+icon.src);assert.equal(b.readUInt32BE(16),Number(icon.sizes.split('x')[0]));}
  console.log('PASS PWA draft restoration, room isolation, refresh guards, offline safety, install control, manifest and PNG dimensions');
})().catch(e=>{console.error(e);process.exit(1);});

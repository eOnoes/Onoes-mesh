'use strict';
const fs=require('fs'), vm=require('vm'), assert=require('assert');
function fixture(options={}){
 const els={};for(const id of ['push-enable','push-sound','push-status'])els[id]={disabled:false,textContent:'',dataset:{},handlers:{},addEventListener(n,f){this.handlers[n]=f;},setAttribute(){}};
 const storage=new Map(), calls=[], prefs=[];
 let sub=null, state={ready:true,enrollment:true,enrolled:false,enabled:false,public_key:Buffer.alloc(65,4).toString('base64url')};
 const subscription={toJSON:()=>({endpoint:'https://fcm.googleapis.com/fcm/send/test',keys:{p256dh:'mock-browser-key',auth:'mock-auth'}}),unsubscribe:async()=>{calls.push('unsubscribe');sub=null;return true;}};
 class Channel{constructor(){this.port1={close(){},onmessage:null};this.port2={postMessage:data=>this.port1.onmessage({data})};}}
 const c={console,URL,URLSearchParams,Uint8Array,atob:s=>Buffer.from(s,'base64').toString('binary'),MessageChannel:Channel,setTimeout,clearTimeout,
 confirm:()=>{calls.push('confirm-off');return options.allowDisable===true;},
 document:{getElementById:id=>els[id]},PushManager:function(){},
 location:{hash:options.noLink?'#relay':'#push_enroll=isolated-one-use&device=Eddie%20phone',pathname:'/',search:''},history:{replaceState(a,b,url){calls.push(['strip',url]);}},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 Notification:{permission:options.permission||'default',requestPermission:async()=>{calls.push('permission');c.Notification.permission=options.deny?'denied':'granted';return c.Notification.permission;}},
 navigator:{serviceWorker:{ready:Promise.resolve({pushManager:{getSubscription:async()=>sub,subscribe:async args=>{assert.strictEqual(args.userVisibleOnly,true);assert.strictEqual(args.applicationServerKey.length,65);calls.push('subscribe');sub=subscription;return sub;}},active:{postMessage:(data,ports)=>{prefs.push(data.silent);ports[0].postMessage({ok:true});}}})}},
 fetch:async(url,init)=>{
  if(options.offline)throw Error('offline');
  if(url.endsWith('/status'))return {ok:true,json:async()=>state};
  const body=JSON.parse(init.body);
  if(url.endsWith('/setup'))return {ok:true,json:async()=>({capability:'isolated-one-use',device:'Eddie phone'})};
  assert.strictEqual(body.device,'Eddie phone');assert(body.subscription&&body.subscription.keys.auth,'empty enrollment payload must fail');
  calls.push([url,body]);
  if(url.endsWith('/enroll')){assert.strictEqual(init.headers.Authorization,'Bearer isolated-one-use');if(options.reject)return{ok:false,json:async()=>({error:'rejected'})};state={...state,enrolled:true,enabled:true,device:body.device};}
  else if(url.endsWith('/revoke')){assert.strictEqual(body.subscription.endpoint,subscription.toJSON().endpoint);state={...state,enrolled:false,enabled:false};}
  return {ok:true,json:async()=>({enrolled:state.enrolled,revoked:!state.enrolled})};
 }};
 if(options.notReady)state.ready=false;
 if(options.ownerSetup)state.owner_setup=true;
 c.window=c;vm.createContext(c);vm.runInContext(fs.readFileSync('push-settings.js','utf8'),c);
 return {c,els,calls,prefs,storage};
}
(async()=>{
 const f=fixture({allowDisable:true});await f.c.meshPush.refresh();assert.strictEqual(f.els['push-enable'].textContent,'turn on');assert.strictEqual(f.els['push-enable'].disabled,false);assert(!f.calls.includes('permission'));
 assert.deepStrictEqual(f.calls[0],['strip','/#relay']);
 await f.els['push-enable'].handlers.click();assert(f.calls.includes('permission'));assert(f.calls.includes('subscribe'));assert.strictEqual(f.els['push-enable'].textContent,'turn off');
 assert.strictEqual(f.storage.get('mesh-push-device-v1'),'Eddie phone');
 await f.els['push-sound'].handlers.click();assert.strictEqual(f.prefs.at(-1),true);assert.strictEqual(f.els['push-sound'].textContent,'silent');
 await f.els['push-enable'].handlers.click();assert(f.calls.includes('unsubscribe'));assert(!f.storage.has('mesh-push-device-v1'));
 const granted=fixture({permission:'granted'});await granted.c.meshPush.refresh();assert.strictEqual(granted.els['push-enable'].textContent,'turn on');await granted.els['push-enable'].handlers.click();assert(granted.calls.includes('subscribe'));assert(!granted.calls.includes('permission'));
 const owner=fixture({noLink:true,ownerSetup:true});await owner.c.meshPush.refresh();assert.strictEqual(owner.els['push-enable'].textContent,'turn on');await owner.els['push-enable'].handlers.click();assert.strictEqual(owner.els['push-enable'].textContent,'turn off');
 await owner.els['push-enable'].handlers.click();assert(owner.calls.includes('confirm-off'));assert.strictEqual(owner.els['push-enable'].textContent,'turn off');assert(!owner.calls.includes('unsubscribe'));assert.strictEqual(owner.calls.filter(c=>Array.isArray(c)&&c[0].endsWith('/revoke')).length,0);
 const noLink=fixture({noLink:true,permission:'granted'});await noLink.c.meshPush.refresh();assert.strictEqual(noLink.els['push-enable'].textContent,'setup required');assert(noLink.els['push-enable'].disabled);
 const unready=fixture({notReady:true});await unready.c.meshPush.refresh();assert(unready.els['push-enable'].disabled);
 const denied=fixture({deny:true});await denied.c.meshPush.refresh();await denied.els['push-enable'].handlers.click();assert(!denied.calls.includes('subscribe'));assert(denied.els['push-enable'].disabled);
 const rejected=fixture({reject:true});await rejected.c.meshPush.refresh();await rejected.els['push-enable'].handlers.click();assert(!rejected.storage.has('mesh-push-device-v1'));assert.strictEqual(rejected.els['push-status'].textContent,'rejected');
 const offline=fixture({offline:true});await offline.c.meshPush.refresh();assert(offline.els['push-enable'].disabled);
 console.log('PASS real browser-shaped subscription/enrollment/revocation contract, permission gates and persistent sound acknowledgment');
})().catch(e=>{console.error(e);process.exit(1);});

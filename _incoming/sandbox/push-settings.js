(() => {
'use strict';
const enable=document.getElementById('push-enable'), sound=document.getElementById('push-sound'), status=document.getElementById('push-status');
if(!enable||!sound||!status)return;
const DK='mesh-push-device-v1', SK='mesh-push-sound-v1';
let capability='',device='',server={},sub=null,busy=false;
const f=new URLSearchParams(window.location.hash.slice(1));
if(f.has('push_enroll')) {capability=f.get('push_enroll')||'';device=f.get('device')||'';window.history.replaceState(null,'',window.location.pathname+window.location.search+'#relay');}
const supported=()=> 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const say=t=>status.textContent=t, own=()=>localStorage.getItem(DK)||'', silent=()=>localStorage.getItem(SK)==='silent';
const enrolled=()=>Boolean(sub&&own()&&server.enrolled&&server.device===own());
function paintSound(){sound.textContent=silent()?'silent':'device default';sound.setAttribute('aria-pressed',String(!silent()));}
function paint(){
 enable.disabled=busy;sound.disabled=busy||!supported();
 if(!supported()){enable.disabled=true;enable.textContent='unsupported';say('Use Chrome with Web Push support.');return;}
 if(enrolled()){enable.textContent='turn off';say(server.enabled?'Phone enrolled. Delivery still needs a phone test.':'Phone enrolled but delivery unavailable. You can turn it off.');return;}
 if(Notification.permission==='denied'){enable.disabled=true;enable.textContent='blocked';say('Allow notifications in Chrome site settings.');return;}
 if(!server.ready){enable.disabled=true;enable.textContent='not ready';say('Phone alerts are not set up on the PC yet.');return;}
 if((!capability||!device)&&!server.owner_setup||!server.enrollment){enable.disabled=true;enable.textContent='setup required';say('Open the one-use setup link supplied by Echo.');return;}
 enable.textContent='turn on';say('Turn on and allow Chrome notifications. Alerts say only New Relay message.');
}
async function post(path,body,token){
 const headers={'Content-Type':'application/json'};if(token)headers.Authorization='Bearer '+token;
 const r=await fetch('/api/relay/push/'+path,{method:'POST',cache:'no-store',credentials:'same-origin',headers,body:JSON.stringify(body)});
 const data=await r.json();if(!r.ok)throw new Error(data.error||'PC refused phone setup.');return data;
}
async function refresh(){
 if(!supported()){paint();return;}
 try{const r=await fetch('/api/relay/push/status',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw Error();server=await r.json();sub=await(await navigator.serviceWorker.ready).pushManager.getSubscription();paint();}
 catch(_){server={};enable.disabled=true;enable.textContent='not ready';say('PC did not answer. Reconnect and retry.');}
}
function key(s){const raw=atob(s.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-s.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));}
async function persistSound(){
 const r=await navigator.serviceWorker.ready;if(!r.active)throw Error('Notification worker not active.');
 await new Promise((resolve,reject)=>{const c=new MessageChannel();const timer=setTimeout(()=>{c.port1.close();reject(Error('Sound preference not saved.'));},5000);c.port1.onmessage=e=>{clearTimeout(timer);c.port1.close();e.data&&e.data.ok?resolve():reject(Error('Sound preference not saved.'));};r.active.postMessage({type:'relay-push-sound',silent:silent()},[c.port2]);});
}
async function enroll(){
 if(!server.ready)throw Error('Phone setup not ready.');
 if(Notification.permission!=='granted'&&await Notification.requestPermission()!=='granted')throw Error('Chrome notification permission not granted.');
 if(!capability||!device){const setup=await post('setup',{});capability=setup.capability;device=setup.device;}
 if(!capability||!device)throw Error('Phone setup not authorized.');
 const r=await navigator.serviceWorker.ready;sub=await r.pushManager.getSubscription();
 if(!sub)sub=await r.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key(server.public_key)});
 await persistSound();await post('enroll',{device,subscription:sub.toJSON()},capability);
 localStorage.setItem(DK,device);capability='';await refresh();
}
async function disable(){
 if(!sub||!own())throw Error('This browser has no enrollment.');
 if(typeof window.confirm!=='function'||!window.confirm('Turn off Relay phone alerts? Cancel keeps them on.')){say('Phone alerts remain on.');return;}
 await post('revoke',{device:own(),subscription:sub.toJSON()});const removed=await sub.unsubscribe();localStorage.removeItem(DK);sub=null;await refresh();if(!removed)say('PC revoked alerts; Chrome cleanup needs retry.');
}
enable.addEventListener('click',async()=>{if(busy||enable.disabled)return;busy=true;paint();try{if(enrolled())await disable();else await enroll();}catch(e){say(e.message||'Phone setup failed.');}finally{busy=false;enable.disabled=!supported()||(!enrolled()&&(!server.ready||!capability||Notification.permission==='denied'));}});
sound.addEventListener('click',async()=>{if(busy||!supported())return;const before=silent();localStorage.setItem(SK,before?'device-default':'silent');try{await persistSound();paintSound();say(silent()?'Silent alerts saved.':'Device-default sound saved. Phone volume and DND apply.');}catch(e){localStorage.setItem(SK,before?'silent':'device-default');paintSound();say(e.message);}});
window.meshPush={refresh,enroll,disable,paint,paintSound};paintSound();refresh();
})();

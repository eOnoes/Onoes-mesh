
// Mesh-only adapter: existing Relay UI, current Mesh proof and confined real routes.
var meshVolatileStorage={values:new Map(),getItem:function(k){return this.values.get(k)||null},setItem:function(k,v){this.values.set(k,String(v))},removeItem:function(k){this.values.delete(k)}};
var meshNativeFetch=window.fetch.bind(window),meshActive=true;
window.fetch=async function(resource,options){
  options=options||{};
  var proof;
  try{proof=JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1')||'null')}catch(e){}
  if(!meshActive||document.visibilityState==='hidden'||!navigator.onLine||!proof||Date.now()>=proof.expiresAt)throw Error('Start a current local session in Mesh before opening Relay.');
  var route=resource.indexOf('/static/')===0?'/api/relay'+resource:'/api/relay/native'+resource,headers=Object.assign({},options.headers,{'X-Trial-CSRF':proof.csrfToken});
  if(/\/message$/.test(resource))route='/api/relay/message';
  var r=await meshNativeFetch(route,Object.assign({},options,{headers:headers,credentials:'same-origin',cache:'no-store'}));var raw=await r.text();if(!meshActive||Date.now()>=proof.expiresAt||document.visibilityState==='hidden')throw Error('Mesh admission changed during Relay response');r=new Response(raw,{status:r.status,headers:r.headers});
  if(r.status===401||(r.status===403&&!raw)){meshClear();throw Error('Mesh session refused or expired. Return to Mesh.');}
  return r;
};
function meshClear(){meshActive=false;A={};outbox=[];pendingFiles=[];cur=null;meshVolatileStorage.values.clear();try{sessionStorage.removeItem('mesh.synthetic-demo.proof.v1')}catch(e){};document.body.replaceChildren();var link=document.createElement('a');link.href='/';link.textContent='Private Relay data cleared. Return to Mesh and start a local session.';document.body.append(link)}
document.getElementById('meshTaskLink').addEventListener('click',function(e){e.preventDefault();window.parent.postMessage({type:'mesh_relay_select',taskId:this.dataset.taskId,instance:document.querySelector('meta[name=mesh-terminal-instance]')?.content},new URL(document.baseURI).origin)});
window.addEventListener('offline',meshClear);
document.addEventListener('visibilitychange',function(){if(document.visibilityState==='hidden')meshClear()});
window.addEventListener('pagehide',function(e){if(e.persisted)meshClear()});
setInterval(function(){var p;try{p=JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1')||'null')}catch(e){};if(meshActive&&(!p||Date.now()>=p.expiresAt))meshClear()},1000);

var A={},cur=null,es=null,drawerOpen=false,drawerView='conversations',followOutput=true,goalViews={},todoExpanded={},goalControlState={};
var pendingFiles=[],outbox=[],outboxSending=false,outboxTimer=null,captureChain=Promise.resolve(),heartbeatBusy=false;
var OUTBOX_KEY='relay-text-outbox-v1';
var $=function(id){return document.getElementById(id)};
var esc=function(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')};
var escAttr=function(s){return esc(s).replace(/"/g,'&quot;')};
// Copy helpers. navigator.clipboard needs a secure context (https or localhost), so
// keep a textarea fallback for any other origin.
function fallbackCopy(text){var ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.top='-1000px';document.body.appendChild(ta);ta.select();var ok=false;try{ok=document.execCommand('copy')}catch(e){ok=false}document.body.removeChild(ta);return ok}
function copyText(text){if(navigator.clipboard&&navigator.clipboard.writeText){return navigator.clipboard.writeText(text).then(function(){return true},function(){return fallbackCopy(text)})}return Promise.resolve(fallbackCopy(text))}
function flashLabel(el,text){if(!el)return;var was=el.getAttribute('data-lbl')||el.textContent;el.setAttribute('data-lbl',was);el.textContent=text;el.classList.add('oky');setTimeout(function(){el.textContent=was;el.classList.remove('oky')},1200)}
function copyFromElement(el,labelEl){var text=el?(el.innerText||el.textContent||''):'';if(!text.trim())return;copyText(text).then(function(ok){flashLabel(labelEl,ok?'copied':'failed')})}
var DOT={working:'var(--green)',stalled:'var(--amber)',waiting:'var(--blue)',stopped:'var(--tx4)',done:'var(--green)',idle:'var(--tx4)'};
var AGENT_COLOR={echo:'#f0a44b',cyony:'#ff79b0',tripp:'#ef6461',dsh:'#6fd3c7'};
var viewportTimers=[];
function scrollLatest(){var sc=$('scr');if(sc)sc.scrollTop=sc.scrollHeight}
// ---- sticky scroll -------------------------------------------------------
// Streaming output used to yank the transcript to the bottom on every event, so
// reading back through an older message was impossible: one SSE tick and you were
// back at the newest line. Following is now a state, not a setting - it is true
// only while the view is already parked at the bottom, and any scroll upward
// leaves it. The jump chip in the corner is the way back down.
var following=true,msgBaseline={};
// 64px of slack. A jump - or the browser's own scroll-to-bottom - lands exactly on
// the bottom, so nothing above this threshold is ever a programmatic scroll.
var BOTTOM_SLACK=64;
function scrEl(){return $('scr')}
function bottomGap(){var sc=$('scr');return sc?sc.scrollHeight-sc.scrollTop-sc.clientHeight:0}
function atBottom(){return bottomGap()<=BOTTOM_SLACK}
function scrollable(){var sc=$('scr');return Boolean(sc)&&sc.scrollHeight-sc.clientHeight>4}
function shouldFollow(){return followOutput&&following}
// Pin to the bottom or hold the exact reading position, in one synchronous write.
// It has to be synchronous: render() replaces the whole transcript with innerHTML,
// which resets scrollTop, and waiting for requestAnimationFrame would leave a frame
// of the old scroll offset on screen.
function syncScroll(pin){
  var sc=$('scr');
  if(!sc)return;
  if(pin)sc.scrollTop=sc.scrollHeight;
  else{var max=sc.scrollHeight-sc.clientHeight;if(sc.scrollTop>max)sc.scrollTop=max<0?0:max}
  syncJump()
}
// An explicit "take me to the bottom": the jump chip, End, a new conversation.
// Always moves, and re-arms following even when the follow setting is off.
function trueJump(){following=true;syncScroll(true)}
// The output itself nudging the view down. Follows only while the setting is on
// AND the reader has not scrolled away.
function followScroll(){if(!followOutput)return;if(!following)return;syncScroll(true)}
function syncViewport(keepLatest){var vv=window.visualViewport;var height=Math.round(vv?vv.height:window.innerHeight);var top=Math.round(vv?vv.offsetTop:0);document.documentElement.style.setProperty('--relay-vh',height+'px');document.documentElement.style.setProperty('--relay-vtop',top+'px');
// Only pin to the newest line when the reader is actually following it. This fired on
// ANY viewport change while the composer had focus - and on a phone the address bar
// hiding or the keyboard settling IS a viewport change, so scrolling up through a long
// reply yanked the view straight back to the end. That was the "internal timer".
if(following&&(keepLatest||document.activeElement===$('in')))requestAnimationFrame(syncScroll)}
function settleViewport(){viewportTimers.forEach(clearTimeout);viewportTimers=[setTimeout(function(){syncViewport(true)},50),setTimeout(function(){syncViewport(true)},220)]}
function storedTextSize(){try{var value=meshVolatileStorage.getItem('relay-text-size');return value==='small'||value==='large'?value:'normal'}catch(e){return 'normal'}}
function storedValue(key,fallback){try{var value=meshVolatileStorage.getItem(key);return value===null?fallback:value}catch(e){return fallback}}
function markSaved(){if($('settingsSaved'))$('settingsSaved').textContent='saved on this device'}
function applyTextSize(size,save){if(size!=='small'&&size!=='large')size='normal';document.documentElement.dataset.textSize=size;$('settingsPanel').querySelectorAll('[data-size]').forEach(function(b){b.setAttribute('aria-checked',String(b.dataset.size===size))});if(save){try{meshVolatileStorage.setItem('relay-text-size',size)}catch(e){}markSaved()}requestAnimationFrame(syncScroll)}
function applyTheme(theme,save){theme=theme==='light'?'light':'dark';document.documentElement.dataset.theme=theme;document.querySelector('meta[name="theme-color"]').setAttribute('content',theme==='light'?'#e7e7e9':'#000000');$('settingsPanel').querySelectorAll('[data-theme-value]').forEach(function(b){b.setAttribute('aria-checked',String(b.dataset.themeValue===theme))});if(save){try{meshVolatileStorage.setItem('relay-theme',theme)}catch(e){}markSaved()}}
function applyFollowOutput(value,save){followOutput=Boolean(value);$('followOutput').setAttribute('aria-checked',String(followOutput));$('followOutput').textContent=followOutput?'on':'off';if(save){try{meshVolatileStorage.setItem('relay-follow-output',followOutput?'on':'off')}catch(e){}markSaved()}}
function resetSettings(){applyTheme('dark',true);applyTextSize('normal',true);applyFollowOutput(true,true)}
function stxt(a){var s=a.status;return s==='working'?'working · turn '+a.goal.turns+'/'+a.goal.max_turns:s==='done'?(a.backend==='openclaw'?'run completed':'goal achieved'):s==='stalled'?'stalled · watchdog':s==='waiting'?'waiting on you':s}
function box(t,right,rows){var h='<div class="bx"><div class="bl"><span class="c">┌</span><span class="fl"></span><span class="c">┐</span></div>';
h+='<div class="bl"><span class="c">│</span><span class="brow"><span class="bt">'+t+'</span><span class="ld"></span>'+(right?'<span class="bxr">'+right+'</span>':'')+'</span><span class="c">│</span></div>';
rows.forEach(function(r){h+='<div class="bl"><span class="c">│</span><span class="brow">'+r+'</span><span class="c">│</span></div>'});
return h+'<div class="bl"><span class="c">└</span><span class="fl"></span><span class="c">┘</span></div></div>'}
function done(a){return (a.goal.steps||[]).filter(function(s){return s&&s[2]==='d'}).length}
function goalFocus(steps){for(var i=steps.length-1;i>=0;i--)if(steps[i]&&steps[i][2]==='a')return i;for(var j=0;j<steps.length;j++)if(steps[j]&&(steps[j][2]==='p'||steps[j][2]==='w'))return j;return Math.max(0,steps.length-1)}
function collapsedGoalIndexes(steps,focus){if(!steps.length)return [];var before=[],after=[],used={};for(var i=focus-1;i>=0&&before.length<2;i--)if(steps[i][2]==='d')before.unshift(i);for(var j=focus+1;j<steps.length&&after.length<2;j++)if(steps[j][2]==='p'||steps[j][2]==='w')after.push(j);if(after.length<2)for(var k=0;k<steps.length&&after.length<2;k++)if(k!==focus&&steps[k][2]!=='d'&&after.indexOf(k)<0)after.push(k);var result=before.concat([focus],after);result.forEach(function(n){used[n]=true});for(var distance=1;result.length<Math.min(5,steps.length)&&distance<steps.length;distance++){[focus-distance,focus+distance].forEach(function(n){if(result.length<5&&n>=0&&n<steps.length&&!used[n]){result.push(n);used[n]=true}})}return result}
function defaultGoalView(){return window.matchMedia&&window.matchMedia('(max-width:600px)').matches?'mini':'focus'}
function goalView(agentId){return goalViews[agentId]||defaultGoalView()}
function nextGoalView(view){return view==='mini'?'focus':view==='focus'?'expanded':'mini'}
function goalStateText(a){var native=a.goal.native_status||a.status;return native==='active'?'in play':native==='done'?'complete':native==='paused'?'paused':native}
function goalRow(step,index,focus){if(!step)return '';var current=index===focus;var state=step[2];var mark=current?'●':state==='d'?'✓':state==='w'?'⚠':'○';var cls=current?'is-current':state==='d'?'is-done':'is-next';return '<div class="goal-row '+cls+'" data-goal-index="'+index+'"><span class="goal-mark">'+mark+'</span><span class="goal-row-text" title="'+escAttr(step[0])+'">'+esc(step[0])+'</span></div>'}
function syncGoalLayout(){var dock=$('goalDock'),bar=document.querySelector('.tbar');document.documentElement.style.setProperty('--tbar-height',(bar?bar.offsetHeight:45)+'px');var visible=Boolean(dock&&!dock.hidden),wide=window.innerWidth>=760;document.documentElement.style.setProperty('--goal-offset',(visible&&!wide?dock.offsetHeight:0)+'px');document.documentElement.style.setProperty('--goal-side-offset',(visible&&wide?dock.offsetWidth+12:0)+'px')}
function goalControls(a){var allowed=a.goal.controls||[];if(!allowed.length)return '';var state=goalControlState[a.id]||{},pending=state.pending,native=a.goal.native_status||a.status,buttons='';if(state.confirmDelete){buttons='<span class="goal-control-note">delete this goal?</span><button class="goal-ctl danger" id="goalDeleteYes">[yes, delete]</button><button class="goal-ctl" id="goalDeleteNo">[cancel]</button>'}else{if(native==='active'&&allowed.indexOf('pause')>=0)buttons+='<button class="goal-ctl" id="goalPause" '+(pending?'disabled':'')+'>[pause]</button>';if(native==='paused'&&allowed.indexOf('resume')>=0)buttons+='<button class="goal-ctl" id="goalResume" '+(pending?'disabled':'')+'>[resume]</button>';if(allowed.indexOf('delete')>=0)buttons+='<button class="goal-ctl danger" id="goalDelete" '+(pending?'disabled':'')+'>[delete]</button>'}var note=pending?'sending '+pending+'…':state.message||'';return '<div class="goal-controls">'+buttons+(note?'<span class="goal-control-note '+(state.error?'error':'')+'">'+esc(note)+'</span>':'')+'</div>'}
function bindGoalControls(a){var bind=function(id,action){var el=$(id);if(el)el.onclick=function(){controlGoal(a.id,action)}};bind('goalPause','pause');bind('goalResume','resume');bind('goalDelete','delete');bind('goalDeleteYes','confirm-delete');bind('goalDeleteNo','cancel-delete')}
function parseTodoText(text){var lines=String(text||'').split(/\r?\n/),heading=-1;for(var i=0;i<lines.length;i++){var clean=lines[i].replace(/^\s*#{1,6}\s*/,'').replace(/[*_`]/g,'').trim();if(/^(?:(?:current\s+.+?\s+|here(?:'s| is)\s+(?:my|the|your)\s+)?(?:to-?do|todo|checklist)(?:\s+list)?|here(?:'s|’s| is)\s+what\s+i\s+currently\s+have\s+tracked)\s*:?$/i.test(clean)){heading=i;break}}if(heading<0)return null;var items=[],started=false;for(var j=heading+1;j<lines.length;j++){var line=lines[j],match=line.match(/^(\s*)(?:(\d+)[.)]\s+|[-*+]\s+(?:\[([ xX])\]\s+)?)(.+?)\s*$/);if(match){started=true;var state=match[3]&&match[3].toLowerCase()==='x'?'d':'p',indent=match[1].replace(/\t/g,'  ').length,depth=Math.min(3,Math.floor(indent/2));items.push(['  '.repeat(depth)+match[4].trim(),' ',state]);continue}if(!line.trim())continue;if(started)break}return items.length>=2?{items:items,heading:lines[heading].replace(/:\s*$/,'').trim()}:null}
function derivedTodo(a){for(var i=(a.msgs||[]).length-1;i>=0;i--){var m=a.msgs[i];if(m.k!=='you'){var parsed=parseTodoText(m.t);if(parsed)return parsed}}return null}
function todoRow(step,index){var state=step[2],mark=state==='d'?'✓':state==='a'?'●':state==='w'?'⚠':'○',cls=state==='d'?'is-done':state==='a'?'is-current':'is-next';return '<div class="goal-row '+cls+'" data-todo-index="'+index+'"><span class="goal-mark">'+mark+'</span><span class="goal-row-text" title="'+escAttr(step[0])+'">'+esc(step[0])+'</span></div>'}
function updateDockVisibility(){
  var dock=$('goalDock'),cards=$('goalCards'),mcp=$('mcpDock');
  if(!dock)return;
  var hasCards=Boolean(cards&&cards.innerHTML.trim());
  var hasMcp=Boolean(mcp&&!mcp.hidden&&mcp.innerHTML.trim());
  dock.hidden=!(hasCards||hasMcp);
  syncGoalLayout();
}
function renderGoal(a){var dock=$('goalDock'),html='',goal=a.goal&&a.goal.text,todo=derivedTodo(a),expandedTodo=Boolean(todoExpanded[a.id]);if(goal){var steps=a.goal.steps||[],focus=goalFocus(steps),view=goalView(a.id),expanded=view==='expanded',mini=view==='mini',indexes=expanded?steps.map(function(_,i){return i}):mini?[]:collapsedGoalIndexes(steps,focus),action=mini?'open':expanded?'minimize':'more',accent=AGENT_COLOR[a.id]||'var(--amber)',rows=indexes.map(function(i){return goalRow(steps[i],i,focus)}).join('');html+='<section class="goal-card '+view+'" style="--goal-accent:'+accent+'"><button class="goal-head" id="goalToggle" aria-expanded="'+(!mini)+'" aria-controls="goalRows" title="cycle goal size"><span class="goal-label">goal <span class="goal-state">· '+esc(goalStateText(a))+'</span></span><span class="ld"></span><span class="goal-progress">'+done(a)+'/'+steps.length+' · turn '+a.goal.turns+'/'+a.goal.max_turns+'</span><span class="goal-action">['+action+']</span></button><div class="goal-objective" title="'+escAttr(a.goal.text)+'">'+esc(a.goal.text)+'</div><div class="goal-rows" id="goalRows">'+rows+'</div>'+goalControls(a)+'</section>'}if(todo){var todoRows=todo.items.map(todoRow).join('');html+='<section class="goal-card todo-card '+(expandedTodo?'expanded':'mini')+'"><button class="goal-head" id="todoToggle" aria-expanded="'+expandedTodo+'" aria-controls="todoRows" title="'+(expandedTodo?'collapse':'expand')+' to-do list"><span class="goal-label">to-do</span><span class="ld"></span><span class="goal-progress">'+todo.items.length+' items</span><span class="goal-action">['+(expandedTodo?'close':'open')+']</span></button><div class="goal-rows" id="todoRows">'+todoRows+'</div></section>'}dock.innerHTML=html;var __cards=$('goalCards');if(__cards)__cards.innerHTML=html;updateDockVisibility();if(goal){$('goalToggle').onclick=function(){goalViews[a.id]=nextGoalView(goalView(a.id));renderGoal(a)};bindGoalControls(a)}if(todo){$('todoToggle').onclick=function(){todoExpanded[a.id]=!expandedTodo;renderGoal(a)}}requestAnimationFrame(function(){syncGoalLayout();if(goal&&goalView(a.id)==='expanded'){var list=$('goalRows'),active=list&&list.querySelector('[data-goal-index="'+goalFocus(a.goal.steps||[])+'"]');if(list&&active)list.scrollTop=Math.max(0,active.offsetTop-list.clientHeight/2+active.offsetHeight/2)}})}
function apprBox(cmd){return box('approval required','',[
'<span style="color:var(--tx)">wants to run:</span>',
'<span style="color:var(--tx)">$ '+esc(cmd)+'</span>',
'<span class="keys"><button class="key y" data-act="approve">[y] approve once</button><button class="key" data-act="approve-always">[a] always allow</button><button class="key" data-act="reject">[n] reject</button></span>'])}
function fsize(n){return n<1024?n+' b':n<1048576?Math.round(n/1024)+' kb':(n/1048576).toFixed(1)+' mb'}
function msgFiles(files){
  if(!files||!files.length)return '';
  // [name.ext] - the bracket is the affordance. Size lives in the tooltip so the
  // transcript line stays as plain as the rest of the terminal.
  return '<div class="chat-files">'+files.map(function(f){
    var n=esc(f.name),z=fsize(f.size);
    if(!f.id)return '<span class="chat-file dead" title="reference only - content was not stored">['+n+']</span>';
    var url='/api/attachments/'+encodeURIComponent(f.id);
    return '<a class="chat-file" href="'+url+'" target="_blank" rel="noopener" title="'+n+' · '+z+'">['+n+']</a>';
  }).join('')+'</div>'
}
function render(){if(!meshActive)return;var a=A[cur];if(!a)return;$('snd').disabled=false;var refs=a.meshTaskLinks||[];if(refs.length){var ref=refs[refs.length-1];$('meshTaskLink').hidden=false;$('meshTaskLink').href='/#task='+encodeURIComponent(ref.task_id);$('meshTaskLink').textContent='Mesh task '+ref.task_id;$('meshTaskLink').dataset.taskId=ref.task_id;}
// Decide from the DOM we are about to throw away: were we parked at the bottom,
// and how far up had we scrolled? innerHTML destroys the scroll position, so the
// answer has to be read before the write.
var sc=$('scr'),wantFollow=shouldFollow(),keepTop=sc?sc.scrollTop:0;
var tabs='';Object.keys(A).forEach(function(k){var x=A[k];tabs+='<button data-testid="agent-tab" class="tab '+(k===cur?'on':'')+'" data-k="'+k+'"><span class="tdot" style="background:'+(DOT[x.status]||DOT.idle)+'"></span>'+esc(x.name)+'</button>'});
$('tabs').innerHTML=tabs;
$('ttl').textContent='relay — '+a.backend+'@'+a.device+' · '+stxt(a);
$('stop').hidden=!(a.status==='working'||a.status==='stalled');
renderGoal(a);
var h='<div class="ln dm">relay · connected to '+esc(a.name.toLowerCase())+(a.backend==='mesh'?' · authenticated snapshots; task links only':' · sse live')+'</div><div class="ln"> </div>';
a.feed.forEach(function(l){h+='<div class="ln f-ln '+(l[1]||'')+'"><span class="f-w" data-copy="line"><span class="fcp" role="button" tabindex="0" title="copy this line">[copy]</span>'+(l[2]?'<span class="ts">'+esc(feedTime(l[2]))+'</span>':'')+'<span class="f-txt">'+esc(l[0])+'</span></span></div>'});
h+='<div class="ln"> </div>';
a.msgs.forEach(function(m){
if(m.k==='you')h+='<div class="ln chat-msg you"><span class="chat-who you-who">YOU</span><span class="chat-body" data-copy="msg">'+esc(m.t)+'<span class="fcp" role="button" tabindex="0" title="copy this message">[copy]</span></span>'+msgFiles(m.attachments)+'</div>';
else h+='<div class="ln chat-msg agent '+esc(a.id)+'"><span class="chat-who agent-who">'+esc(a.name)+'</span><span class="chat-body" data-copy="msg">'+esc(m.t)+(m.t?'<span class="fcp" role="button" tabindex="0" title="copy this message">[copy]</span>':'')+'</span>'+msgFiles(m.attachments)+'</div>'});
if(a.approval&&a.approval.cmd){var approvalHtml=apprBox(a.approval.cmd);if(a.backend==='openclaw')approvalHtml=approvalHtml.replace(/<button[^>]*data-act="approve-always"[^>]*>.*?<\/button>/,'');h+=approvalHtml}
if(a.status==='stalled')h+='<div class="ln keys"><button class="key y" data-act="nudge">[nudge]</button><button class="key" data-act="stop">[stop]</button></div>';
if(a.goal&&a.goal.budget_enforced===false)h+='<div class="ln dm">Native outer runs: '+a.goal.turns+' · budget '+a.goal.max_turns+' is display only; internal model iterations unavailable</div>';if(a.connection==='disconnected')h+='<div class="ln wr">Tripp gateway disconnected · reconnecting; task outcome not yet known</div>';if(a.status==='working')h+='<div class="ln thinking"><span class="cur"></span> '+esc((a.name||'agent').toLowerCase())+' is thinking<span class="dots"><i>.</i><i>.</i><i>.</i></span></div>';
if(a.status==='idle')h+='<div class="ln dm">'+(a.backend==='mesh'?'idle · send to create one Workroom task; no command execution':'idle · send a message to start a run')+'</div>';
if(a.feed.length===0&&a.msgs.length===0&&a.status==='idle'){if(a.backend==='hermes'&&a.device==='pc')h+='<div class="ln dm">tip: “/goal <text>” starts a planned run with live steps</div>';else if(a.backend==='a2a')h+='<div class="ln dm">a2a peer · chat, streaming and stop. tool progress, approvals and goals need an on-host bridge</div>'}
$('scr').innerHTML=h;
// Pin if we were following, otherwise put the reader back exactly where they were.
// This used to be the unconditional `if(followOutput)scrollLatest()`, which is what
// dragged the view to the newest line mid-read.
if(wantFollow)syncScroll(true);
else{sc.scrollTop=keepTop;countAway();syncJump()}
$('in').disabled=false;syncComposer();
$('tabs').querySelectorAll('.tab').forEach(function(b){b.onclick=function(){connect(b.dataset.k)}});
$('scr').querySelectorAll('[data-act]').forEach(function(b){b.onclick=function(){act(b.dataset.act)}})}

// ---- jump-to-latest chip -------------------------------------------------
// Two independent reasons to show it: the reader has scrolled up (they may simply
// want back down), or new messages landed while they were away (worth a count).
function awayCount(){var a=A[cur],total=a&&a.msgs?a.msgs.length:0,baseline=msgBaseline[cur];return baseline===undefined?0:Math.max(0,total-baseline)}
function countAway(){var a=A[cur];if(a&&a.msgs)msgBaseline[cur]=a.msgs.length}
function syncJump(){
  var btn=$('jumpDown'),label=$('jumpCount'),sc=$('scr');
  // Keep the chip clear of the composer however tall it grows with the draft.
  var cmp=document.querySelector('.cmp');
  if(cmp)document.documentElement.style.setProperty('--cmp-h',cmp.offsetHeight+'px');
  if(!btn||!sc)return;
  var newMsgs=following?0:awayCount(),show=!following&&scrollable();
  btn.hidden=!show;
  if(!show)return;
  if(label){label.hidden=!newMsgs;label.textContent=newMsgs?String(newMsgs):''}
  var text=newMsgs===1?'1 new message since you scrolled up':newMsgs?newMsgs+' new messages since you scrolled up':'jump to the latest message';
  btn.setAttribute('aria-label',text);
  btn.title=text;
}
function jumpToLatest(){trueJump();countAway()}
// Offline honesty at the point of interaction, not after the fact. Previously the
// composer looked completely normal while nothing could leave: you only found out
// by sending and watching the message queue. Now the wording says so when you click
// in, and the border tints.
function syncComposer(){
  var inp=$('in'),a=A[cur],cmp=document.querySelector('.cmp');
  if(!inp)return;
  var off=!navigator.onLine;
  if(cmp)cmp.classList.toggle('offline',off);
  if(!inp.disabled)inp.placeholder=off?'offline · messages queue here until you reconnect':((a?a.name:'relay')+' · type a message…');
  if(off)showOutbox('offline · waiting',true);
}
window.addEventListener('online',function(){syncComposer();drainOutbox()});
window.addEventListener('offline',function(){syncComposer()});
$('in').addEventListener('focus',syncComposer);
function snapshotAsText(agent){
  if(!agent)return '';
  var lines=[agent.name+' ('+agent.backend+')'+(agent.conversation_id?' · conversation '+agent.conversation_id:'')];
  (agent.msgs||[]).forEach(function(m){
    if(m.k!=='you'&&m.k!=='ag')return;
    var who=m.k==='you'?'YOU':String(agent.name).toUpperCase();
    lines.push('');
    lines.push(who+': '+String(m.t||''));
  });
  return lines.join('\n');
}
function apply(a,ev){if(ev.type==='snapshot'){A[cur]=ev.agent}
else if(ev.type==='status'){a.status=ev.status}
else if(ev.type==='goal'){a.goal=ev.goal}
else if(ev.type==='step'){var s=a.goal.steps[ev.idx];if(s){s[2]=ev.state;if(ev.stamp)s[1]=ev.stamp}}
else if(ev.type==='turns'){a.goal.turns=ev.turns}
else if(ev.type==='feed'){a.feed.push([ev.text,ev.cls||'',ev.ts||''])}
else if(ev.type==='msg'){a.msgs.push({k:ev.k,t:ev.t,attachments:ev.attachments||[]})}
else if(ev.type==='approval'){a.approval=ev.cmd?{id:ev.id,cmd:ev.cmd}:null}}
function showDrawerView(view){drawerView=view==='settings'?'settings':'conversations';var settings=drawerView==='settings';$('conversationsPanel').hidden=settings;$('settingsPanel').hidden=!settings;$('drawerSettings').setAttribute('aria-pressed',String(settings));$('drawerKicker').textContent=settings?'relay':'conversations';if(settings){$('drawerAgent').textContent='settings';$('drawerAgent').style.color='var(--tx)'}else{var a=A[cur];$('drawerAgent').textContent=a?a.name:'conversations';$('drawerAgent').style.color=AGENT_COLOR[cur]||'var(--tx)';if(drawerOpen)loadSessions()}}
function closeDrawer(){if(!drawerOpen)return;drawerOpen=false;$('drawer').classList.remove('on');$('drawer').setAttribute('aria-hidden','true');$('scrim').classList.remove('on');$('menu').setAttribute('aria-expanded','false');setTimeout(function(){if(!drawerOpen)$('scrim').hidden=true},170)}
function ago(value){var ms=Date.now()-Date.parse(value);if(!Number.isFinite(ms)||ms<60000)return 'just now';var mins=Math.floor(ms/60000);if(mins<60)return mins+'m ago';var hours=Math.floor(mins/60);if(hours<24)return hours+'h ago';var days=Math.floor(hours/24);return days+'d ago'}
function renderSessions(list){if(!list.length){$('sessionList').innerHTML='<div class="session-empty">No conversations yet.</div>';return}$('sessionList').innerHTML=list.map(function(s){return '<button class="session '+(s.active?'on':'')+'" data-session="'+esc(s.id)+'"><span class="session-title">'+esc(s.title)+'</span><span class="session-preview">'+esc(s.preview||'No messages yet')+'</span><span class="session-time">'+ago(s.updated_at)+'</span></button>'}).join('');$('sessionList').querySelectorAll('[data-session]').forEach(function(b){b.onclick=function(){activateSession(b.dataset.session)}})}
async function loadSessions(){var k=cur,a=A[k];if(!a||drawerView!=='conversations')return;$('drawerAgent').textContent=a.name;$('drawerAgent').style.color=AGENT_COLOR[k]||'var(--tx)';$('drawerError').textContent='';$('sessionList').innerHTML='<div class="session-empty">loading conversations…</div>';try{var r=await fetch('/api/agents/'+k+'/sessions'),body=await r.json();if(!r.ok||!body.ok)throw Error(body.error||'could not load conversations');renderSessions(body.sessions)}catch(e){$('drawerError').textContent=e.message;$('sessionList').innerHTML=''}}
function openDrawer(){if(drawerOpen){closeDrawer();return}drawerOpen=true;showDrawerView('conversations');$('scrim').hidden=false;renderMcp();fetchMcp(cur,true);renderActivity();fetchActivity(cur,true);requestAnimationFrame(function(){$('scrim').classList.add('on');$('drawer').classList.add('on')});$('drawer').setAttribute('aria-hidden','false');$('menu').setAttribute('aria-expanded','true')}
async function activateSession(id){var k=cur;closeDrawer();$('cmperr').textContent='';if(es)es.close();try{var r=await post('sessions/'+encodeURIComponent(id)+'/activate',{},k),body=await r.json();if(!r.ok||!body.ok)throw Error(body.error||'could not open conversation');connect(k)}catch(e){$('cmperr').textContent=e.message;connect(k)}}
async function newSession(){var k=cur;closeDrawer();$('cmperr').textContent='';if(es)es.close();try{var r=await post('sessions',{},k),body=await r.json();if(!r.ok||!body.ok)throw Error(body.error||'could not start conversation');connect(k)}catch(e){$('cmperr').textContent=e.message;connect(k)}}
function connect(k){closeDrawer();if(es)es.close();hideCmdPop();cur=k;meshVolatileStorage.setItem('relay-agent',k);renderCmdPop();
// Opening, activating or starting a conversation is an explicit request to see the
// newest message: start pinned and re-arm following even if the setting is off.
following=true;delete msgBaseline[k];
// Queue state belongs to the agent on screen: clear the previous agent's notice
// and show this one's own pending count instead of a leftover error.
$('cmperr').textContent='';showOutbox('',false);renderOutboxErrors();
render();showOutbox('',false);renderOutboxErrors();drainOutbox()}
async function heartbeat(){if(heartbeatBusy||!meshActive)return;heartbeatBusy=true;try{var r=await fetch('/api/agents'),list=await r.json();if(!r.ok||!Array.isArray(list))throw Error('Actual Relay unavailable');if(!meshActive)return;if(!Array.isArray(list))throw Error('Actual isolated Relay unavailable. Return to Mesh to reconnect.');list.forEach(function(a){A[a.id]=a});render()}catch(e){if(meshActive)$('ttl').textContent='relay unavailable — return to Mesh to reconnect'}finally{heartbeatBusy=false}}
function post(path,body,agentId){return fetch('/api/agents/'+(agentId||cur)+'/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})})}
async function controlGoal(agentId,action){var a=A[agentId],state=goalControlState[agentId]||(goalControlState[agentId]={});if(!a||state.pending)return;if(action==='delete'){state.confirmDelete=true;state.message='';state.error=false;renderGoal(a);return}if(action==='cancel-delete'){state.confirmDelete=false;state.message='';state.error=false;renderGoal(a);return}if(action==='confirm-delete')action='delete';state.confirmDelete=false;state.pending=action;state.message='';state.error=false;renderGoal(a);try{var response=await post('goal/control',{action:action},agentId),result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'goal action failed');if(result.goal)A[agentId].goal=result.goal;state.message=action==='delete'?'goal deleted':action==='pause'?'goal paused':'goal resumed'}catch(e){state.message=e.message||'goal action failed';state.error=true}finally{state.pending='';if(cur===agentId)render()}}
async function act(action){var k=cur,a=A[k],body={},route=action;if(action==='nudge')body.id=crypto.randomUUID();if(action==='stop'){if(a.activeRunIds&&a.activeRunIds.length===1)body.runId=a.activeRunIds[0]}if(action==='approve'||action==='approve-always'||action==='reject'){route='approve';body={id:a.approval&&a.approval.id,approved:action!=='reject',always:action==='approve-always'}}try{var response=await post(route,body,k),result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Action failed')}catch(e){$('cmperr').textContent=e.message}}
function renderFiles(){$('attbar').innerHTML=pendingFiles.map(function(f,i){return '<span class="att"><span class="att-name">'+esc(f.name)+'</span><span class="att-size">'+fsize(f.size)+'</span><button class="att-rm" data-rm="'+i+'" aria-label="remove '+esc(f.name)+'">×</button></span>'}).join('');$('attbar').querySelectorAll('[data-rm]').forEach(function(b){b.onclick=function(){pendingFiles.splice(Number(b.dataset.rm),1);renderFiles()}})}
function filePayload(f){return new Promise(function(resolve,reject){var r=new FileReader();r.onload=function(){resolve({name:f.name,type:f.type||'application/octet-stream',data:r.result})};r.onerror=function(){reject(new Error('could not read '+f.name))};r.readAsDataURL(f)})}
function loadOutbox(){
  try{var saved=JSON.parse(meshVolatileStorage.getItem(OUTBOX_KEY)||'[]')}catch(e){saved=[]}
  if(!Array.isArray(saved))saved=[];
  outbox=saved.filter(function(x){return x&&x.id&&x.agentId&&typeof x.text==='string'}).map(function(x){
    return {id:x.id,agentId:x.agentId,text:x.text,files:[],attempts:Number(x.attempts)||0,
            error:x.error||'',nextAttempt:Number(x.nextAttempt)||0}});
}
function persistOutbox(){try{var durable=outbox.filter(function(x){return !x.files||!x.files.length}).map(function(x){return {id:x.id,agentId:x.agentId,text:x.text,attempts:x.attempts||0,error:x.error||'',nextAttempt:x.nextAttempt||0}});meshVolatileStorage.setItem(OUTBOX_KEY,JSON.stringify(durable))}catch(e){}}
// Queue state is PER AGENT. The outbox holds messages for every agent, so the
// indicator and any error must be scoped to the one on screen, and a stuck agent
// must never hold up another agent's message.
function agentOutbox(agentId){return outbox.filter(function(x){return x.agentId===agentId})}
function showOutbox(note,retrying){
  var el=$('queueState'),clear=$('queueClear');
  if(!el)return;
  var mine=agentOutbox(cur);
  if(!mine.length){el.textContent='';el.classList.remove('retrying');if(clear)clear.hidden=true;return}
  el.textContent=mine.length+' message'+(mine.length===1?'':'s')+' queued'+(note?' · '+note:'');
  el.classList.toggle('retrying',Boolean(retrying));
  if(clear)clear.hidden=false;
}
function discardQueue(){
  var mine=agentOutbox(cur);
  if(!mine.length)return;
  outbox=outbox.filter(function(x){return x.agentId!==cur});
  persistOutbox();
  var el=$('cmperr');if(el)el.textContent='';
  showOutbox('',false);
}
function renderOutboxErrors(){var el=$('cmperr');if(!el)return;var pending=agentOutbox(cur).filter(function(x){return x.error});el.textContent=pending.length?(pending[0].error||'connection interrupted'):''}
function scheduleOutbox(delay){clearTimeout(outboxTimer);outboxTimer=setTimeout(drainOutbox,delay)}
async function sendQueued(item){var controller=new AbortController(),timer=setTimeout(function(){controller.abort()},30000);try{var response=await fetch('/api/agents/'+item.agentId+'/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:item.id,text:item.text,conversationId:A[item.agentId].conversation_id,meshIntent:'create_task'}),signal:controller.signal});var body={};try{body=await response.json()}catch(e){}if(!response.ok||!body.ok){var error=new Error(body.error||('send failed · '+response.status));error.status=response.status;throw error}if(!meshActive)throw Error('Relay page inactive');$('meshTaskLink').hidden=false;$('meshTaskLink').href='/#task='+encodeURIComponent(body.taskId);$('meshTaskLink').textContent='Mesh task '+body.taskId;$('meshTaskLink').dataset.taskId=body.taskId;heartbeat();return body}finally{clearTimeout(timer)}}
// Pure scheduling core for the outbox, kept free of DOM and network so it is
// testable. Returns {sent, failed, soonest}. One agent being down must not stop
// another agent's messages: each entry retries on its own backoff schedule.
async function deliverOutbox(items,sendOne,now){
  var sent=0,failed=0,soonest=null;
  for(var i=0;i<items.length;i++){
    var item=items[i];
    var at=Number(item.nextAttempt)||0;
    if(now()<at){soonest=Math.min(soonest===null?Infinity:soonest,at);continue}
    try{
      await sendOne(item);
      item.delivered=true;item.error='';item.nextAttempt=0;sent++;
    }catch(e){
      item.attempts=(Number(item.attempts)||0)+1;
      item.error=(e&&e.message)||'connection interrupted';
      var delay=Math.min(30000,1000*Math.pow(2,Math.min(item.attempts,5)));
      item.nextAttempt=now()+delay;
      soonest=Math.min(soonest===null?Infinity:soonest,item.nextAttempt);
      failed++;
    }
  }
  return {sent:sent,failed:failed,soonest:soonest};
}
async function drainOutbox(){
  if(outboxSending||!outbox.length)return;
  if(!navigator.onLine){showOutbox('offline · waiting',true);scheduleOutbox(3000);return}
  outboxSending=true;
  var mine=agentOutbox(cur);
  if(mine.length)showOutbox('sending',false);
  var result;
  try{
    result=await deliverOutbox(outbox,function(item){
      return sendQueued(item).then(function(v){
        if(item.agentId===cur)$('cmperr').textContent='';
        return v;
      });
    },function(){return Date.now()});
  }finally{
    outboxSending=false;
  }
  outbox=outbox.filter(function(x){return !x.delivered});
  persistOutbox();
  renderOutboxErrors();
  showOutbox(result.sent?'':(result.soonest?'connection interrupted · retrying':''),
             !result.sent&&Boolean(result.soonest));
  if(outbox.length)scheduleOutbox(result.soonest?Math.max(500,result.soonest-Date.now()):1000);
}
function send(){if(!meshActive)return;if(pendingFiles.length){$('cmperr').textContent='Mesh task messages support text only.';return}var target=cur,v=$('in').value.trim(),picked=pendingFiles.slice();if(!v&&!picked.length)return;$('in').value='';sizeComposer();pendingFiles=[];renderFiles();$('cmperr').textContent='';hideCmdPop();captureChain=captureChain.then(async function(){var files=await Promise.all(picked.map(filePayload));outbox.push({id:crypto.randomUUID(),agentId:target,text:v,files:files,attempts:0,error:'',nextAttempt:0});persistOutbox();showOutbox('',false);drainOutbox()}).catch(function(e){$('cmperr').textContent=e.message||'could not queue message'})}
// ---- MCP panel ----------------------------------------------------------
// Per-agent MCP servers. Only a local Hermes install is inspectable; for A2A and
// OpenClaw the server reports honestly that the state is not observable, and the
// panel says so rather than showing an empty list.
var MCP_CACHE={},mcpBusy=false;
function mcpMark(status){return status==='running'?'ok':(status==='idle'?'idle':'off')}
function renderMcpHtml(report){
  if(!report)return '<div class="mcp-head"><span class="mcp-title">mcp</span><span class="mcp-count">loading…</span></div><div class="mcp-note">reading server state…</div>';
  var head='<div class="mcp-head"><span class="mcp-title">mcp</span><span class="mcp-count">'
    +(report.supported===false?'not observable':(report.servers||[]).length+' servers')+'</span></div>';
  if(report.supported===false){
    return head+'<div class="mcp-note">'+esc(report.reason||'MCP state is not exposed by this transport')+'</div>';
  }
  var servers=report.servers||[];
  if(!servers.length)return head+'<div class="mcp-note">'+esc(report.note||'no MCP servers configured')+'</div>';
  var rows=servers.map(function(s){
    return '<div class="mcp-live" title="'+escAttr(s.detail||'')+'">'
      +'<span class="mcp-mark '+mcpMark(s.status)+'"></span>'
      +'<span class="mcp-name">'+esc(s.name)+'</span>'
      +'<span class="mcp-transport">'+esc(s.status==='running'?'running':(s.status==='disabled'?'disabled':s.transport))+'</span>'
      +'</div>';
  }).join('');
  var note=report.note?'<div class="mcp-note">'+esc(report.note)+'</div>':'';
  return head+rows+note;
}
function renderMcp(){
  var report=MCP_CACHE[cur];
  var dock=$('mcpDock'),drawer=$('mcpDrawer');
  if(dock){dock.innerHTML=renderMcpHtml(report);dock.hidden=!report}
  if(drawer){drawer.innerHTML=renderMcpHtml(report);drawer.hidden=!report}
  updateDockVisibility();
}
function fetchMcp(agentId,force){
  var cached=MCP_CACHE[agentId];
  if(!force&&cached&&(Date.now()-(cached._at||0))<30000){renderMcp();return}
  if(mcpBusy)return;
  mcpBusy=true;
  fetch('/api/agents/'+agentId+'/mcps').then(function(r){return r.json()}).then(function(report){
    report._at=Date.now();MCP_CACHE[agentId]=report;
    if(cur===agentId)renderMcp();
  }).catch(function(){
    MCP_CACHE[agentId]={ok:false,supported:false,reason:'could not read MCP state'};
    if(cur===agentId)renderMcp();
  }).then(function(){mcpBusy=false});
}
// ---- activity trail -----------------------------------------------------
// Durable per-agent record of what actually happened (tools, runs, approvals,
// delegations). Unlike the live feed it survives a Relay restart, so it is what
// you review after something went wrong.
var ACT_CACHE={};
function actTime(iso){var d=new Date(iso);if(isNaN(d.getTime()))return String(iso||'').slice(11,19);return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})}
// The feed stamp arrives as ISO UTC and is rendered in the device's own timezone.
// Same width as the old server-formatted "HH:MM" so nothing moves on screen, and the
// fallback keeps an unexpected value readable instead of printing "Invalid Date".
function feedTime(iso){var d=new Date(iso);if(isNaN(d.getTime()))return String(iso||'').slice(0,5);return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',hour12:false})}
function renderActivity(){
  var el=$('actDrawer');
  if(!el)return;
  var data=ACT_CACHE[cur];
  if(!data||!data.activity||!data.activity.length){el.hidden=true;el.innerHTML='';return}
  var html='<div class="act-head">activity<span class="act-count">'+data.count+' recorded</span></div>';
  html+=data.activity.map(function(r){
    var ms=(r.duration_ms!==null&&r.duration_ms!==undefined)?'<span class="act-ms">'+Math.round(r.duration_ms)+'ms</span>':'';
    var detail=r.detail?' · '+esc(r.detail):'';
    return '<div class="act-row">'
      +'<span class="act-ts">'+esc(actTime(r.ts))+'</span>'
      +'<span class="act-kind '+esc(r.kind)+'">'+esc(r.kind)+'</span>'
      +'<span class="act-txt" title="'+escAttr((r.name||'')+(r.detail?' — '+r.detail:''))+'">'+esc(r.name)+ms+detail+'</span>'
      +'</div>';
  }).join('');
  el.innerHTML=html;el.hidden=false;
}
function fetchActivity(agentId,force){
  var cached=ACT_CACHE[agentId];
  if(!force&&cached&&(Date.now()-(cached._at||0))<15000){renderActivity();return}
  fetch('/api/agents/'+agentId+'/activity?limit=150').then(function(r){return r.json()}).then(function(data){
    data._at=Date.now();ACT_CACHE[agentId]=data;
    if(cur===agentId)renderActivity();
  }).catch(function(){});
}
// ---- slash-command autocomplete ----------------------------------------
// Catalogs are dumped from each backend's REAL command registry:
//   hermes   -> tools/dump_slash_commands.py    (Hermes gateway COMMAND_REGISTRY)
//   openclaw -> tools/dump-openclaw-commands.mjs (OpenClaw commands-registry.shared.ts)
// so every suggestion is a command that agent's runtime actually dispatches.
var SLASH_CATALOGS={hermes:[],openclaw:[]},cmdSel=0,cmdOpen=false,cmdBlurTimer=null;
fetch('/static/slash-commands.json').then(function(r){return r.ok?r.json():[]}).then(function(list){SLASH_CATALOGS.hermes=Array.isArray(list)?list:[]}).catch(function(){});
fetch('/static/slash-commands-openclaw.json').then(function(r){return r.ok?r.json():[]}).then(function(list){SLASH_CATALOGS.openclaw=Array.isArray(list)?list:[]}).catch(function(){});
// Which catalog applies to the selected agent. A2A peers run Hermes but cannot
// execute operator commands remotely, so they get the Hermes list plus a note.
function catalogFor(backend){return backend==='openclaw'?SLASH_CATALOGS.openclaw:SLASH_CATALOGS.hermes}
// Pure matcher, tiered like Hermes' own fuzzy menu: exact > prefix > substring
// > description. Aliases count as names. Returns the ranked list.
function cmdMatches(list,q){
  var query=String(q||'').replace(/^\/+/,'').toLowerCase();
  var exact=[],prefix=[],sub=[],desc=[];
  (list||[]).forEach(function(c){
    var names=[c.name].concat(c.aliases||[]);
    if(!query){prefix.push(c);return}
    if(names.some(function(n){return n.toLowerCase()===query}))exact.push(c);
    else if(names.some(function(n){return n.toLowerCase().indexOf(query)===0}))prefix.push(c);
    else if(names.some(function(n){return n.toLowerCase().indexOf(query)>=0}))sub.push(c);
    else if(String(c.desc||'').toLowerCase().indexOf(query)>=0)desc.push(c);
  });
  return exact.concat(prefix,sub,desc);
}
function hideCmdPop(){cmdOpen=false;cmdSel=0;var pop=$('cmdPop');if(pop){pop.hidden=true;pop.innerHTML='';pop._matches=[]}}
function renderCmdPop(){
  var pop=$('cmdPop'),inp=$('in');
  if(!pop||!inp)return;
  var v=inp.value;
  var a=A[cur];
  var catalog=catalogFor(a&&a.backend);
  // Only suggest while the first token is being typed ("/go…"); once there is a
  // space the command is complete and Enter must send again.
  if(!/^\/\S*$/.test(v)||!catalog.length){hideCmdPop();return}
  var matches=cmdMatches(catalog,v);
  if(!matches.length){hideCmdPop();return}
  if(cmdSel>=matches.length)cmdSel=0;
  cmdOpen=true;pop._matches=matches;
  var note='';
  if(a&&a.backend==='a2a')note='<div class="cmdnote">'+esc(a.name)+' (a2a) · commands are sent as plain text — remote peers do not execute them</div>';
  else if(a&&a.backend==='openclaw')note='<div class="cmdnote">'+esc(a.name)+' · OpenClaw commands — availability depends on his gateway config</div>';
  pop.innerHTML=note+matches.map(function(c,i){
    var alias=c.aliases&&c.aliases.length?' <span class="cmdalias">'+c.aliases.map(function(x){return '/'+esc(x)}).join(' ')+'</span>':'';
    return '<div class="cmdrow'+(i===cmdSel?' sel':'')+'" role="option" aria-selected="'+(i===cmdSel)+'" data-i="'+i+'"><span class="cmdname">/'+esc(c.name)+alias+'</span><span class="cmddesc">'+esc(c.desc||'')+'</span></div>';
  }).join('');
  pop.hidden=false;
  var cmp=document.querySelector('.cmp');
  pop.style.bottom=((cmp?cmp.offsetHeight:60)+8)+'px';
  var sel=pop.querySelector('.cmdrow.sel');
  if(sel)sel.scrollIntoView({block:'nearest'});
  pop.querySelectorAll('.cmdrow').forEach(function(row){
    row.addEventListener('click',function(e){e.preventDefault();clearTimeout(cmdBlurTimer);applyCmd(matches[Number(row.dataset.i)])});
  });
}
function applyCmd(c){
  if(!c)return;
  $('in').value='/'+c.name+' ';
  hideCmdPop();
  $('in').focus();
}
$('in').addEventListener('input',function(){cmdSel=0;renderCmdPop()});
$('in').addEventListener('focus',function(){renderCmdPop()});
$('in').addEventListener('blur',function(){cmdBlurTimer=setTimeout(hideCmdPop,250)});
$('add').onclick=function(){$('files').click()};
$('queueClear').onclick=discardQueue;
$('files').onchange=function(){var picked=Array.from(this.files||[]);$('cmperr').textContent='';if(pendingFiles.length+picked.length>4){$('cmperr').textContent='choose no more than 4 attachments';picked=picked.slice(0,Math.max(0,4-pendingFiles.length))}pendingFiles=pendingFiles.concat(picked);this.value='';renderFiles()};
$('menu').onclick=openDrawer;
$('scrim').onclick=closeDrawer;
$('drawerClose').onclick=closeDrawer;
$('drawerSettings').onclick=function(){showDrawerView(drawerView==='settings'?'conversations':'settings')};
$('settingsBack').onclick=function(){showDrawerView('conversations')};
$('settingsPanel').querySelectorAll('[data-size]').forEach(function(b){b.onclick=function(){applyTextSize(b.dataset.size,true)}});
$('settingsPanel').querySelectorAll('[data-theme-value]').forEach(function(b){b.onclick=function(){applyTheme(b.dataset.themeValue,true)}});
// ------------------------------------------------------------- notifications --
// Per-device, so it lives in settings rather than in the chat view. The server decides
// whether subscribing is even possible: /api/notifications/vapid returns 503 until a
// signing key exists, and the copy says so instead of offering a switch that cannot work.
function deepLinkAgent(){try{var m=/[#&]agent=([^&]+)/.exec(location.hash||'');return m?decodeURIComponent(m[1]):''}catch(e){return ''}}
function pushCopy(text){var el=$('pushCopy');if(el)el.textContent=text}
function setPushToggle(on,label){var b=$('pushToggle');if(!b)return;b.setAttribute('aria-checked',String(!!on));b.textContent=label||(on?'on':'off')}
// The Push API wants the VAPID key as bytes, not base64url.
function keyBytes(base64){var pad='='.repeat((4-base64.length%4)%4);var raw=atob((base64+pad).replace(/-/g,'+').replace(/_/g,'/'));var out=new Uint8Array(raw.length);for(var i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out}
function pushAvailable(){return ('serviceWorker' in navigator)&&('PushManager' in window)&&('Notification' in window)}
async function refreshPush(){
  if(!pushAvailable()){setPushToggle(false,'n/a');pushCopy('this browser cannot receive push notifications');return}
  try{
    var reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();
    if(sub){setPushToggle(true,'on');pushCopy('this device is subscribed — deep links open the exact item');return}
    if(Notification.permission==='denied'){setPushToggle(false,'blocked');pushCopy('notifications are blocked for this site in your browser settings');return}
    setPushToggle(false,'off');pushCopy('approvals and failures reach this device even when the app is closed');
  }catch(e){setPushToggle(false,'off');pushCopy('could not read push state: '+(e.message||e))}
}
async function enablePush(){
  if(!pushAvailable()){pushCopy('this browser cannot receive push notifications');return}
  try{
    if(await Notification.requestPermission()!=='granted'){setPushToggle(false,'blocked');pushCopy('permission was not granted');return}
    var key=await fetch('/api/notifications/vapid').then(function(r){return r.json()});
    if(!key.ok){setPushToggle(false,'off');pushCopy(key.error||'push is not configured on the server yet');return}
    var reg=await navigator.serviceWorker.ready;
    var sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(key.public_key)});
    var body=sub.toJSON();
    var saved=await fetch('/api/notifications/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint:body.endpoint,keys:body.keys,device:(navigator.userAgent||'').slice(0,60)})}).then(function(r){return r.json()});
    if(!saved.ok){try{await sub.unsubscribe()}catch(e){}setPushToggle(false,'off');pushCopy(saved.error||'the server refused the subscription');return}
    setPushToggle(true,'on');
    pushCopy(saved.enabled?'this device is subscribed':'subscribed — the server still has push switched off');
  }catch(e){setPushToggle(false,'off');pushCopy('could not subscribe: '+(e.message||e))}
}
async function disablePush(){
  try{
    var reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();
    if(sub)await sub.unsubscribe();
    setPushToggle(false,'off');pushCopy('this device will not receive push notifications');
  }catch(e){pushCopy('could not unsubscribe: '+(e.message||e))}
}
if($('pushToggle'))$('pushToggle').onclick=function(){if($('pushToggle').getAttribute('aria-checked')==='true')disablePush();else enablePush()};
// Reports the outcome per channel rather than a bare success, because "it sent" and "it
// arrived" are different claims and only the second one is the point of a test.
if($('pushTest'))$('pushTest').onclick=async function(){
  var b=$('pushTest');b.disabled=true;pushCopy('sending…');
  try{
    var r=await fetch('/api/notifications/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent:cur})}).then(function(x){return x.json()});
    if(!r.ok){pushCopy(r.error||'could not send the test');return}
    var d=(r.result&&r.result.delivery)||{},names=Object.keys(d);
    var sent=names.filter(function(n){return d[n]&&d[n].ok});
    if(sent.length){pushCopy('sent via '+sent.join(', ')+' — check your phone')}
    else if(names.length){pushCopy('no channel accepted it: '+names.map(function(n){return n+' ('+((d[n]&&d[n].reason)||'failed')+')'}).join(', '))}
    else{pushCopy('the notification was recorded, but no channel is configured to deliver it')}
  }catch(e){pushCopy('could not send the test: '+(e.message||e))}
  finally{b.disabled=false}
};
refreshPush();
$('followOutput').onclick=function(){applyFollowOutput(!followOutput,true);if(followOutput){following=true;syncScroll(true)}else syncJump()};
$('resetSettings').onclick=resetSettings;
$('newSession').onclick=newSession;
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDrawer()});
$('snd').onclick=send;
$('in').onkeydown=function(e){
  if(cmdOpen){
    var matches=($('cmdPop')||{})._matches||[];
    if(matches.length){
      if(e.key==='ArrowDown'){e.preventDefault();cmdSel=(cmdSel+1)%matches.length;renderCmdPop();return}
      if(e.key==='ArrowUp'){e.preventDefault();cmdSel=(cmdSel-1+matches.length)%matches.length;renderCmdPop();return}
      if(e.key==='Tab'){e.preventDefault();applyCmd(matches[cmdSel]);return}
      if(e.key==='Enter'){e.preventDefault();applyCmd(matches[cmdSel]);return}
    }
    if(e.key==='Escape'){e.preventDefault();hideCmdPop();return}
  }
  // End (or Ctrl+End) is the keyboard twin of the jump chip.
  if(e.key==='End'&&!(e.shiftKey||e.altKey)){e.preventDefault();jumpToLatest();return}
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}
  else if(e.key==='Enter'&&e.shiftKey)setTimeout(sizeComposer,0);
};
// Shift+Enter adds a line; the box grows with the draft up to a cap, then scrolls.
function sizeComposer(){var t=$('in');if(!t)return;t.style.height='auto';t.style.height=t.scrollHeight+'px'}
$('in').addEventListener('input',function(){sizeComposer()});
$('in').addEventListener('focus',function(){syncViewport(true);settleViewport()});
$('in').addEventListener('blur',function(){syncViewport(false);setTimeout(function(){syncViewport(false)},220)});
$('stop').onclick=function(){act('stop')};
applyTheme(storedValue('relay-theme','dark'),false);
applyTextSize(storedTextSize(),false);
applyFollowOutput(storedValue('relay-follow-output','on')!=='off',false);
loadOutbox();showOutbox('',false);
syncViewport(false);
window.addEventListener('resize',function(){syncViewport(document.activeElement===$('in'))},{passive:true});
if(window.visualViewport){window.visualViewport.addEventListener('resize',function(){syncViewport(document.activeElement===$('in'))},{passive:true});window.visualViewport.addEventListener('scroll',function(){syncViewport(document.activeElement===$('in'))},{passive:true})}
// The reader letting go of the bottom. Nothing is programmatic above
// BOTTOM_SLACK, so any scroll further up than that is a deliberate move away
// from the newest output - stop following and offer the way back.
$('scr').addEventListener('scroll',function(){if(!atBottom()){following=false;syncJump()}},{passive:true});
// Output that grows the transcript after render() has already run - a wrapped
// line in a late image, an attachment row, the goal dock pushing the padding
// down. Re-pin while following, re-clamp otherwise, and keep the chip honest.
if(window.ResizeObserver){var scrollObserver=new ResizeObserver(function(){if(following)syncScroll(true);else syncScroll(false)});scrollObserver.observe($('scr'))}
$('jumpDown').onclick=jumpToLatest;
$('scr').addEventListener('click',function(e){
  var btn=e.target.closest?e.target.closest('.fcp'):null;
  if(!btn)return;
  var holder=btn.closest('[data-copy]');
  if(!holder)return;
  e.preventDefault();
  var clone=holder.cloneNode(true);
  // Strip the affordance and the timestamp: neither belongs in pasted text.
  clone.querySelectorAll('.fcp,.ts').forEach(function(n){n.remove()});
  var text=clone.innerText||clone.textContent||'';
  copyText(text).then(function(ok){flashLabel(btn,ok?'[copied]':'[failed]')});
});
$('copyAll').addEventListener('click',function(){
  var text=snapshotAsText(A[cur]);
  if(!text.trim()){flashLabel($('copyAll'),'nothing');return}
  copyText(text).then(function(ok){flashLabel($('copyAll'),ok?'copied':'failed')});
});
window.addEventListener('online',drainOutbox);
window.addEventListener('focus',heartbeat);
document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible'){heartbeat();drainOutbox()}});
setInterval(function(){if(document.visibilityState==='visible')heartbeat()},30000);
if(window.ResizeObserver){var goalLayoutObserver=new ResizeObserver(syncGoalLayout);goalLayoutObserver.observe(document.querySelector('.tbar'));goalLayoutObserver.observe($('goalDock'))}
// Gate: show the unlock form instead of a wall of failed requests. The token is
// exchanged once for a long-lived cookie, so this appears once per device.
function showGate(){var g=$('gate');if(g)g.hidden=false;var t=$('gateToken');if(t)t.focus()}
function bootRelay(){fetch('/api/agents').then(function(r){return r.json()}).then(function(list){
  if(!meshActive)return;if(!Array.isArray(list))throw Error('Actual isolated Relay unavailable. Return to Mesh to reconnect.');list.forEach(function(a){A[a.id]=a});
  // Phase 2.5: a notification's deep link wins over the remembered agent. `bootRelay`
  // runs from both the already-authenticated path and the post-unlock path, so the link
  // survives the gate by construction -- landing on the conversation list after
  // unlocking is a failure of the notification, not of the user.
  var wanted=deepLinkAgent(),remembered=meshVolatileStorage.getItem('relay-agent');
  connect(A[wanted]?wanted:(A[remembered]?remembered:list[0]&&list[0].id));heartbeat();
}).catch(function(e){if(meshActive){$('ttl').textContent=e.message||'Actual Relay unavailable';$('in').disabled=true;$('snd').disabled=true}})}
fetch('/api/auth').then(function(r){return r.json()}).then(function(s){
  if(s&&s.auth_enabled&&!s.authed){showGate();return}
  bootRelay();
}).catch(function(){bootRelay()});
$('gateForm').addEventListener('submit',function(e){
  e.preventDefault();
  var token=$('gateToken').value;$('gateErr').textContent='';
  fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token})})
    .then(function(r){return r.json().then(function(b){return {ok:r.ok,body:b}})})
    .then(function(res){
      if(!res.ok||!res.body.ok){$('gateErr').textContent=res.body.error||'unlock failed';return}
      $('gateToken').value='';$('gate').hidden=true;bootRelay();
    })
    .catch(function(){$('gateErr').textContent='could not reach relay'});
});
// Mesh-only shell never installs a second service worker or caches conversation bodies.

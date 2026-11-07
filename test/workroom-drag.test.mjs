import test from 'node:test';
import assert from 'node:assert/strict';
import {bindCardDrag} from '../public/workroom-drag.mjs';
function fixture(){
 const listeners={};let capture=false,timer=null;
 const card={style:{},isConnected:true,addEventListener:(n,f)=>(listeners[n]??=[]).push(f),setPointerCapture:()=>capture=true,hasPointerCapture:()=>capture,releasePointerCapture:()=>capture=false};
 const lane={style:{},dataset:{workroomStage:'working'}};lane.closest=()=>lane;
 const board={children:[lane],contains:x=>x===lane,scrollLeft:0,getBoundingClientRect:()=>({left:0,right:800})};
 let target=lane,busy=false;const moved=[];const document={hidden:false,elementFromPoint:()=>target};
 bindCardDrag({card,board,onMove:x=>moved.push(x),isBusy:()=>busy,document,setTimer:f=>(timer=f,1),clearTimer:()=>timer=null});
 return{card,moved,document,hold(){const f=timer;timer=null;f?.();},setTarget:x=>target=x,setBusy:x=>busy=x,
 fire(n,args={}){const touch={identifier:1,clientX:100,clientY:100};const e={button:0,pointerId:1,pointerType:'mouse',clientX:100,clientY:100,target:card,touches:[touch],changedTouches:[touch],preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;},...args};for(const f of listeners[n]||[])f(e);return e;}};
}
const touch=(x=100,y=100)=>({identifier:1,clientX:x,clientY:y});

test('mouse drag from whole card moves and suppresses opening; next click opens',()=>{const f=fixture();f.fire('pointerdown');f.fire('pointermove',{clientX:400});f.fire('pointerup');assert.deepEqual(f.moved,['working']);assert.equal(f.fire('click').stopped,true);f.fire('pointerdown');f.fire('pointerup');assert.equal(f.fire('click').stopped,undefined);});
test('ordinary click or tiny movement opens normally',()=>{const f=fixture();f.fire('pointerdown');f.fire('pointermove',{clientX:103});f.fire('pointerup');assert.deepEqual(f.moved,[]);assert.equal(f.fire('click').stopped,undefined);});
test('quick touch tap opens without moving; delayed timer cannot start a drag',()=>{const f=fixture();f.fire('touchstart');f.fire('touchend');f.hold();assert.deepEqual(f.moved,[]);assert.equal(f.fire('click').stopped,undefined);assert.equal(f.card.style.opacity,'');});
test('immediate swipe retains native scrolling, cancels hold and never moves',()=>{const f=fixture();f.fire('touchstart');const e=f.fire('touchmove',{touches:[touch(100,150)]});assert.equal(e.prevented,undefined);assert.equal(f.fire('click').stopped,true);f.hold();f.fire('touchmove',{touches:[touch(400,150)]});f.fire('touchend');assert.deepEqual(f.moved,[]);assert.equal(f.card.style.opacity,'');});
test('hold anywhere then drag moves once without opening details',()=>{const f=fixture();f.fire('pointerdown',{pointerType:'touch'});f.fire('touchstart');f.hold();assert.equal(f.card.style.opacity,'.5');const e=f.fire('touchmove',{touches:[touch(400)]});assert.equal(e.prevented,true);f.fire('touchend',{changedTouches:[touch(400)]});assert.deepEqual(f.moved,['working']);assert.equal(f.fire('click').stopped,true);});
test('stationary hold does not move or accidentally open',()=>{const f=fixture();f.fire('touchstart');f.hold();f.fire('touchend');assert.deepEqual(f.moved,[]);assert.equal(f.fire('click').stopped,true);});
test('touch cancellation, multitouch, hidden page and detached card cannot move',()=>{for(const mode of ['cancel','multi','hidden','detached','busy']){const f=fixture();f.fire('touchstart');if(mode==='cancel')f.fire('touchcancel');if(mode==='multi')f.fire('touchstart',{touches:[touch(),{...touch(),identifier:2}]});if(mode==='hidden')f.document.hidden=true;if(mode==='detached')f.card.isConnected=false;if(mode==='busy')f.setBusy(true);f.hold();f.fire('touchmove',{touches:[touch(400)]});f.fire('touchend');assert.deepEqual(f.moved,[],mode);}});
test('pointer cancel, foreign pointer, outside drop and busy state cannot move',()=>{for(const mode of ['cancel','foreign','outside','busy']){const f=fixture();if(mode==='busy')f.setBusy(true);f.fire('pointerdown');if(mode==='cancel')f.fire('pointercancel');if(mode==='outside')f.setTarget(null);f.fire('pointermove',{clientX:400,pointerId:mode==='foreign'?2:1});f.fire('pointerup');assert.deepEqual(f.moved,[],mode);}});

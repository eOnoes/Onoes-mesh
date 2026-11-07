export function bindCardDrag({card,board,onMove,isBusy,document,setTimer=setTimeout,clearTimer=clearTimeout}){
  let drag=null,holdTimer=null,suppressClick=false;
  const clean=()=>{
    if(holdTimer!==null)clearTimer(holdTimer);holdTimer=null;
    for(const lane of board.children)lane.style.outline='';
    card.style.opacity='';card.style.cursor='';card.classList?.remove('is-dragging');drag=null;
  };
  const activate=()=>{card.style.opacity='.5';card.style.cursor='grabbing';card.classList?.add('is-dragging');};
  const track=(x,y)=>{
    const lane=document.elementFromPoint(x,y)?.closest('[data-workroom-stage]');
    drag.target=lane&&board.contains(lane)?lane.dataset.workroomStage:null;
    for(const node of board.children)node.style.outline=node===lane?'2px solid var(--accent)':'';
    const bounds=board.getBoundingClientRect();
    if(x<bounds.left+40)board.scrollLeft-=18;
    if(x>bounds.right-40)board.scrollLeft+=18;
  };
  card.addEventListener('dragstart',e=>e.preventDefault());
  card.addEventListener('contextmenu',e=>e.preventDefault());
  // Mouse/pen move after a small distance; an ordinary click still opens details.
  // Touch is handled below: touch-action:none would break ordinary scrolling.
  card.addEventListener('pointerdown',e=>{
    if(e.pointerType==='touch'||isBusy()||e.button!==0||drag)return;
    const capture=e.target.closest?.('button')||card;
    suppressClick=false;drag={kind:'pointer',id:e.pointerId,x:e.clientX,y:e.clientY,moved:false,target:null,capture};
    capture.setPointerCapture(e.pointerId);
  });
  card.addEventListener('pointermove',e=>{
    if(drag?.kind!=='pointer'||e.pointerId!==drag.id)return;
    if(!drag.moved&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<8)return;
    e.preventDefault();drag.moved=true;activate();track(e.clientX,e.clientY);
  });
  card.addEventListener('pointerup',e=>{
    if(drag?.kind!=='pointer'||e.pointerId!==drag.id)return;
    const target=drag.moved?drag.target:null,capture=drag.capture;suppressClick=drag.moved;clean();
    if(capture.hasPointerCapture(e.pointerId))capture.releasePointerCapture(e.pointerId);
    if(target)onMove(target);
  });
  card.addEventListener('pointercancel',()=>{if(drag?.kind==='pointer'){suppressClick=false;clean();}});
  card.addEventListener('lostpointercapture',()=>{if(drag?.kind==='pointer')clean();});
  // Before the hold threshold, a swipe belongs to the browser. Once held, a
  // non-passive touchmove can reserve that gesture for cross-column dragging.
  card.addEventListener('touchstart',e=>{
    if(e.touches.length!==1){suppressClick=Boolean(drag?.armed);clean();return;}
    if(isBusy()||drag)return;
    const touch=e.touches[0];suppressClick=false;
    drag={kind:'touch',id:touch.identifier,x:touch.clientX,y:touch.clientY,armed:false,moved:false,target:null};
    holdTimer=setTimer(()=>{
      holdTimer=null;
      if(drag?.kind!=='touch')return;
      if(isBusy()||document.hidden||card.isConnected===false){clean();return;}
      drag.armed=true;activate();
    },350);
  },{passive:true});
  card.addEventListener('touchmove',e=>{
    if(drag?.kind!=='touch')return;
    if(e.touches.length!==1){suppressClick=drag.armed;clean();return;}
    const touch=Array.from(e.touches).find(t=>t.identifier===drag.id);if(!touch)return;
    const distance=Math.hypot(touch.clientX-drag.x,touch.clientY-drag.y);
    if(!drag.armed){if(distance>=8){suppressClick=true;clean();}return;}
    e.preventDefault();
    if(distance<8&&!drag.moved)return;
    drag.moved=true;track(touch.clientX,touch.clientY);
  },{passive:false});
  card.addEventListener('touchend',e=>{
    if(drag?.kind!=='touch'||!Array.from(e.changedTouches).some(t=>t.identifier===drag.id))return;
    const target=drag.armed&&drag.moved?drag.target:null;
    suppressClick=drag.armed;
    if(drag.armed)e.preventDefault();
    clean();if(target)onMove(target);
  },{passive:false});
  card.addEventListener('touchcancel',()=>{suppressClick=Boolean(drag?.armed);clean();});
  card.addEventListener('click',e=>{if(suppressClick){suppressClick=false;e.preventDefault();e.stopImmediatePropagation();}},true);
}

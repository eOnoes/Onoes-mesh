// Preserve only ephemeral board position; no storage or task mutations.
export function captureBoardView(board,document){
  const active=board.contains(document.activeElement)?document.activeElement:null;
  return {taskId:active?.dataset?.taskId??null,
    sourceLane:active?.closest('[data-workroom-stage]')?.dataset.workroomStage??null,
    left:board.scrollLeft,
    lanes:Array.from(board.querySelectorAll('[data-workroom-stage]'),lane=>({
      key:lane.dataset.workroomStage,top:lane.querySelector('.workroom-stack')?.scrollTop??0
    }))};
}
export function restoreBoardView(board,state){
  for(const lane of board.querySelectorAll('[data-workroom-stage]')){
    const saved=state.lanes.find(item=>item.key===lane.dataset.workroomStage);
    const stack=lane.querySelector('.workroom-stack');if(saved&&stack)stack.scrollTop=saved.top;
  }
  board.scrollLeft=state.left;
  if(state.taskId){
    const card=Array.from(board.querySelectorAll('[data-task-id]')).find(node=>node.dataset.taskId===state.taskId);
    card?.focus({preventScroll:true});
    const lane=card?.closest('[data-workroom-stage]');
    // A move may place the focused card outside a scrolled destination. Reveal
    // only that column; refreshes must preserve the reader's existing position.
    if(card&&state.sourceLane&&lane?.dataset.workroomStage!==state.sourceLane){
      const stack=lane?.querySelector('.workroom-stack');
      if(stack?.clientHeight>0){
        const viewport=stack.getBoundingClientRect(),box=card.getBoundingClientRect();
        const top=viewport.top+stack.clientTop,bottom=top+stack.clientHeight;
        if(box.height>stack.clientHeight||box.top<top)stack.scrollTop+=box.top-top;
        else if(box.bottom>bottom)stack.scrollTop+=box.bottom-bottom;
      }
    }
  }
}

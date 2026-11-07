// Preserve only ephemeral board position; no storage or task mutations.
export function captureBoardView(board,document){
  const active=document.activeElement;
  return {taskId:board.contains(active)?active?.dataset?.taskId:null,
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
  }
}
